"""
使用 esptool 的 ESP32 最小刷新助手。
Examples:
    python flash.py --port COM3 --baud 460800 --bin esp32/firmware.bin
"""
import argparse
import json
import os
import sys

try:
    import esptool  # type: ignore
except Exception as exc:
    print("esptool not installed; install with `pip install esptool`", file=sys.stderr)
    raise


def parse_args():
    parser = argparse.ArgumentParser(description="Flash ESP32 firmware")
    parser.add_argument("--chip", choices=["esp32", "esp32s3"], default=None, help="Target chip (default: esp32; use esp32s3 for S3 boards)")
    parser.add_argument("--port", help="Serial port, e.g. COM3 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=460800, help="Baud rate (default: 460800)")
    parser.add_argument("--bin", required=True, help="Application binary path")
    parser.add_argument("--offset", default="0x10000", help="Flash offset for main binary (e.g. 0x10000 for app w/ bootloader, 0x0 or 0x1000 for MicroPython)")
    parser.add_argument("--bootloader", help="Optional bootloader binary path")
    parser.add_argument("--partitions", help="Optional partitions binary path")
    parser.add_argument("--erase", action="store_true", help="Erase flash before writing")
    return parser.parse_args()


def resolve_port(cli_port):
    """Resolve serial port from CLI, env FLASH_PORT, or esp32_config.json."""
    if cli_port:
        return cli_port

    env_port = os.environ.get("FLASH_PORT")
    if env_port:
        return env_port

    cfg_path = os.path.join(os.path.dirname(__file__), "esp32", "esp32_config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("serial_port")
    except Exception:
        return None


def resolve_chip(cli_chip):
    """Resolve chip type from CLI or env FLASH_CHIP; default esp32."""
    if cli_chip:
        return cli_chip
    env_chip = os.environ.get("FLASH_CHIP")
    if env_chip:
        return env_chip
    return "esp32"


def main():
    args = parse_args()
    chip = resolve_chip(args.chip)
    port = resolve_port(args.port)

    if not port:
        print("Serial port not provided; use --port, set FLASH_PORT, or add serial_port to esp32_config.json", file=sys.stderr)
        sys.exit(1)
    bin_path = os.path.abspath(args.bin)
    if not os.path.exists(bin_path):
        print(f"Binary not found: {bin_path}", file=sys.stderr)
        sys.exit(1)

    cmd = [
        "--chip",
        chip,
        "--port",
        port,
        "--baud",
        str(args.baud),
    ]

    if args.erase:
        esptool.main(cmd + ["erase_flash"])

    flash_cmd = cmd + ["write_flash", "-z"]
    if args.bootloader:
        flash_cmd += ["0x1000", os.path.abspath(args.bootloader)]
    if args.partitions:
        flash_cmd += ["0x8000", os.path.abspath(args.partitions)]

    # Application binary at configurable offset
    flash_cmd += [args.offset, bin_path]
    esptool.main(flash_cmd)


if __name__ == "__main__":
    main()
