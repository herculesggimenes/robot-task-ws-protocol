use nusb::transfer::{Control, ControlType, Recipient, RequestBuffer};
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixListener;
use tokio::sync::Mutex;

// gs_usb constants
const GS_USB_BREQ_HOST_FORMAT: u8 = 0;
const GS_USB_BREQ_BITTIMING: u8 = 1;
const GS_USB_BREQ_MODE: u8 = 2;
const GS_USB_BREQ_BT_CONST: u8 = 4;

const GS_CAN_MODE_START: u32 = 1;
const GS_CAN_MODE_RESET: u32 = 0;

// CANable 2.0 gs_usb VID/PID
const VID: u16 = 0x1d50;
const PID: u16 = 0x606f;

/// Wire protocol over Unix socket:
/// Send frame:    [0x01] [can_id: u32 LE] [dlc: u8] [data: 8 bytes] = 14 bytes
/// Recv frame:    [0x02] [can_id: u32 LE] [dlc: u8] [data: 8 bytes] = 14 bytes
const CMD_SEND: u8 = 0x01;
const CMD_RECV: u8 = 0x02;
const FRAME_SIZE: usize = 14;

struct GsUsbDevice {
    interface: nusb::Interface,
}

impl GsUsbDevice {
    fn open(device_index: usize) -> Result<Self, Box<dyn std::error::Error>> {
        let devices: Vec<_> = nusb::list_devices()
            .map_err(|e| format!("Failed to list USB devices: {e}"))?
            .filter(|d| d.vendor_id() == VID && d.product_id() == PID)
            .collect();

        if devices.is_empty() {
            return Err("No CANable gs_usb device found".into());
        }
        if device_index >= devices.len() {
            return Err(format!(
                "Device index {device_index} out of range, found {} devices",
                devices.len()
            )
            .into());
        }

        let device = devices[device_index].open()?;
        let interface = device.detach_and_claim_interface(0)?;
        eprintln!("Opened CANable device #{device_index}");
        Ok(Self { interface })
    }

    fn set_host_format(&self) -> Result<(), Box<dyn std::error::Error>> {
        // Host format: little-endian u32 = 0x0000BEEF
        let data: [u8; 4] = 0x0000BEEFu32.to_le_bytes();
        let _result = self.interface.control_out_blocking(
            Control {
                control_type: ControlType::Vendor,
                recipient: Recipient::Interface,
                request: GS_USB_BREQ_HOST_FORMAT,
                value: 1,
                index: 0,
            },
            &data,
            std::time::Duration::from_secs(1),
        )?;
        Ok(())
    }

    fn get_bt_const(&self) -> Result<(u32, u32, u32, u32, u32, u32, u32), Box<dyn std::error::Error>>
    {
        let mut buf = [0u8; 40];
        let n = self.interface.control_in_blocking(
            Control {
                control_type: ControlType::Vendor,
                recipient: Recipient::Interface,
                request: GS_USB_BREQ_BT_CONST,
                value: 0,
                index: 0,
            },
            &mut buf,
            std::time::Duration::from_secs(1),
        )?;
        if n < 40 {
            return Err(format!("BT_CONST response too short: {n} bytes").into());
        }
        let feature = u32::from_le_bytes(buf[0..4].try_into()?);
        let fclk = u32::from_le_bytes(buf[4..8].try_into()?);
        let tseg1_min = u32::from_le_bytes(buf[8..12].try_into()?);
        let tseg1_max = u32::from_le_bytes(buf[12..16].try_into()?);
        let tseg2_min = u32::from_le_bytes(buf[16..20].try_into()?);
        let tseg2_max = u32::from_le_bytes(buf[20..24].try_into()?);
        let brp_min = u32::from_le_bytes(buf[28..32].try_into()?);
        Ok((feature, fclk, tseg1_min, tseg1_max, tseg2_min, tseg2_max, brp_min))
    }

    fn set_bittiming(
        &self,
        prop_seg: u32,
        phase_seg1: u32,
        phase_seg2: u32,
        sjw: u32,
        brp: u32,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut data = [0u8; 20];
        data[0..4].copy_from_slice(&prop_seg.to_le_bytes());
        data[4..8].copy_from_slice(&phase_seg1.to_le_bytes());
        data[8..12].copy_from_slice(&phase_seg2.to_le_bytes());
        data[12..16].copy_from_slice(&sjw.to_le_bytes());
        data[16..20].copy_from_slice(&brp.to_le_bytes());
        self.interface.control_out_blocking(
            Control {
                control_type: ControlType::Vendor,
                recipient: Recipient::Interface,
                request: GS_USB_BREQ_BITTIMING,
                value: 0,
                index: 0,
            },
            &data,
            std::time::Duration::from_secs(1),
        )?;
        Ok(())
    }

    fn start(&self) -> Result<(), Box<dyn std::error::Error>> {
        let mut data = [0u8; 8];
        data[0..4].copy_from_slice(&GS_CAN_MODE_START.to_le_bytes());
        data[4..8].copy_from_slice(&0u32.to_le_bytes()); // flags = normal mode
        self.interface.control_out_blocking(
            Control {
                control_type: ControlType::Vendor,
                recipient: Recipient::Interface,
                request: GS_USB_BREQ_MODE,
                value: 0,
                index: 0,
            },
            &data,
            std::time::Duration::from_secs(1),
        )?;
        eprintln!("CAN bus started");
        Ok(())
    }

    fn stop(&self) -> Result<(), Box<dyn std::error::Error>> {
        let mut data = [0u8; 8];
        data[0..4].copy_from_slice(&GS_CAN_MODE_RESET.to_le_bytes());
        data[4..8].copy_from_slice(&0u32.to_le_bytes());
        self.interface.control_out_blocking(
            Control {
                control_type: ControlType::Vendor,
                recipient: Recipient::Interface,
                request: GS_USB_BREQ_MODE,
                value: 0,
                index: 0,
            },
            &data,
            std::time::Duration::from_secs(1),
        )?;
        Ok(())
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let device_index: usize = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let socket_path = format!("/tmp/can{device_index}.sock");

    // Clean up stale socket
    let _ = std::fs::remove_file(&socket_path);

    let dev = GsUsbDevice::open(device_index)?;

    // Query device capabilities
    let (feature, fclk, ..) = dev.get_bt_const()?;
    eprintln!("Device: features=0x{feature:x}, fclk={fclk}Hz");

    // Set host format
    dev.set_host_format()?;

    // Set bit timing for 1Mbps
    // For 170MHz clock: BRP=10, prop_seg=1, phase_seg1=13, phase_seg2=2, sjw=2
    if fclk == 170_000_000 {
        dev.set_bittiming(1, 13, 2, 2, 10)?;
        eprintln!("Bit timing set for 170MHz @ 1Mbps");
    } else if fclk == 48_000_000 {
        dev.set_bittiming(1, 12, 2, 1, 3)?;
        eprintln!("Bit timing set for 48MHz @ 1Mbps");
    } else if fclk == 80_000_000 {
        dev.set_bittiming(1, 12, 2, 1, 5)?;
        eprintln!("Bit timing set for 80MHz @ 1Mbps");
    } else {
        return Err(format!("Unsupported clock frequency: {fclk}Hz").into());
    }

    // Start CAN bus
    dev.start()?;

    // Get bulk endpoints
    let bulk_out = dev.interface.bulk_out_queue(0x02);
    let mut bulk_in = dev.interface.bulk_in_queue(0x81);

    // Pre-submit read requests to keep the IN endpoint fed
    const NUM_IN_FLIGHT: usize = 8;
    for _ in 0..NUM_IN_FLIGHT {
        bulk_in.submit(RequestBuffer::new(64));
    }

    let bulk_out = Arc::new(Mutex::new(bulk_out));
    let bulk_in = Arc::new(Mutex::new(bulk_in));

    // Start Unix socket server
    let listener = UnixListener::bind(&socket_path)?;
    eprintln!("Listening on {socket_path}");

    // Handle Ctrl+C gracefully
    let dev_for_shutdown = Arc::new(dev);
    let dev_clone = dev_for_shutdown.clone();
    let socket_path_clone = socket_path.clone();
    tokio::spawn(async move {
        tokio::signal::ctrl_c().await.ok();
        eprintln!("\nShutting down...");
        dev_clone.stop().ok();
        std::fs::remove_file(&socket_path_clone).ok();
        std::process::exit(0);
    });

    loop {
        let (stream, _) = listener.accept().await?;
        let (mut reader, writer) = stream.into_split();
        let bulk_out = bulk_out.clone();
        let bulk_in = bulk_in.clone();

        eprintln!("Client connected");

        tokio::spawn(async move {
            // Spawn a task to read from USB and forward to client
            let bulk_in_rx = bulk_in.clone();
            let mut writer = writer;
            let rx_task = tokio::spawn(async move {
                loop {
                    let completion = {
                        let mut queue = bulk_in_rx.lock().await;
                        // Wait for next completed transfer
                        futures_lite::future::poll_fn(|cx| queue.poll_next(cx)).await
                    };

                    // Resubmit immediately
                    {
                        let mut queue = bulk_in_rx.lock().await;
                        queue.submit(RequestBuffer::new(64));
                    }

                    match completion.status {
                        Ok(()) => {
                            let data = completion.data;
                            if data.len() >= 20 {
                                // gs_usb frame: echo_id(4) + can_id(4) + can_dlc(1) + channel(1) + flags(1) + reserved(1) + data(8)
                                let echo_id =
                                    u32::from_le_bytes(data[0..4].try_into().unwrap());
                                // Skip TX echo frames — only forward actual RX from the bus
                                // echo_id=0x00000000 is our TX echo, 0xFFFFFFFF is real RX
                                if echo_id != 0xFFFFFFFF {
                                    // Still need to resubmit the read
                                    continue;
                                }
                                let can_id =
                                    u32::from_le_bytes(data[4..8].try_into().unwrap()) & 0x1FFFFFFF;
                                let dlc = data[8].min(8);
                                let mut frame = [0u8; FRAME_SIZE];
                                frame[0] = CMD_RECV;
                                frame[1..5].copy_from_slice(&can_id.to_le_bytes());
                                frame[5] = dlc;
                                frame[6..14].copy_from_slice(&data[12..20]);
                                if writer.write_all(&frame).await.is_err() {
                                    break;
                                }
                            }
                        }
                        Err(e) => {
                            eprintln!("USB read error: {e}");
                            break;
                        }
                    }
                }
            });

            // Read from client and send to USB
            let mut cmd_buf = [0u8; FRAME_SIZE];
            loop {
                match reader.read_exact(&mut cmd_buf).await {
                    Ok(_) => {
                        if cmd_buf[0] == CMD_SEND {
                            let can_id =
                                u32::from_le_bytes(cmd_buf[1..5].try_into().unwrap());
                            let dlc = cmd_buf[5].min(8);

                            // Build gs_usb TX frame: echo_id(4) + can_id(4) + can_dlc(1) + channel(1) + flags(1) + reserved(1) + data(8) = 20 bytes
                            let mut usb_frame = vec![0u8; 20];
                            usb_frame[0..4].copy_from_slice(&0u32.to_le_bytes()); // echo_id
                            usb_frame[4..8].copy_from_slice(&can_id.to_le_bytes());
                            usb_frame[8] = dlc;
                            // channel=0, flags=0, reserved=0
                            usb_frame[12..20].copy_from_slice(&cmd_buf[6..14]);

                            let mut queue = bulk_out.lock().await;
                            queue.submit(usb_frame);
                            let completion =
                                futures_lite::future::poll_fn(|cx| queue.poll_next(cx)).await;
                            if let Err(e) = completion.status {
                                eprintln!("USB write error: {e}");
                                break;
                            }
                        }
                    }
                    Err(_) => break,
                }
            }

            rx_task.abort();
            eprintln!("Client disconnected");
        });
    }
}
