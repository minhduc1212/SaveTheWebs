import argparse
import asyncio
from pathlib import Path

from src.archive import ArchiveIndex
from src.server import WaybackServer
from src.recorder import WebRecorder
from src.utils import DEFAULT_ARCHIVE

def main():
    ap = argparse.ArgumentParser(
        description="WebRecorder v2 – Wayback Machine style archiver",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  # Ghi website (mở browser thật để tương tác)
  python webrecorder.py https://example.com

  # Ghi nhiều site vào cùng 1 kho
  python webrecorder.py https://site1.com
  python webrecorder.py https://site2.com

  # Ghi headless (tự động, không hiện browser)
  python webrecorder.py https://example.com --headless

  # Khởi động replay server (Wayback style)
  python webrecorder.py --replay

  # Dùng kho khác
  python webrecorder.py https://example.com -a my_archive
  python webrecorder.py --replay -a my_archive
  
  # Liệt kê snapshots
  python webrecorder.py --list
  python webrecorder.py --list -a my_archive
        """
    )
    ap.add_argument("url", nargs="?", help="URL cần ghi lại")
    ap.add_argument("-a", "--archive", default=DEFAULT_ARCHIVE,
                    help=f"Thư mục kho lưu trữ (default: {DEFAULT_ARCHIVE})")
    ap.add_argument("--headless", action="store_true", help="Ẩn browser")
    ap.add_argument("--timeout", type=int, default=60, help="Timeout (giây)")
    ap.add_argument("--replay", action="store_true", help="Chạy replay server")
    ap.add_argument("--port", type=int, default=8080, help="Port replay server")
    ap.add_argument("--list", action="store_true", help="Liệt kê snapshots đã lưu")
    ap.add_argument("--scroll-pause", type=float, default=0.5,
                    help="Giây chờ giữa mỗi bước cuộn (auto-scroll, default: 0.5)")
    ap.add_argument("--max-scrolls", type=int, default=100,
                    help="Số lần cuộn tối đa (default: 100)")
    args = ap.parse_args()

    if args.list:
        idx = ArchiveIndex(args.archive)
        snaps = idx.data["snapshots"]
        if not snaps:
            print("Kho trống. Chưa có snapshot nào.")
            return
        print(f"\n{'═'*70}")
        print(f"  Kho: {Path(args.archive).resolve()}  ({len(snaps)} snapshots)")
        print(f"{'═'*70}")
        for s in sorted(snaps, key=lambda x: x["recorded_at"], reverse=True):
            print(f"  📸 {s['id']}")
            print(f"     URL    : {s['url']}")
            print(f"     Assets : {s.get('asset_count', 0)}  |  API: {s.get('api_count', 0)}")
            print(f"     Time   : {s['recorded_at']}")
            print()
    elif args.replay:
        WaybackServer(args.archive, args.port).start()
    elif args.url:
        rec = WebRecorder(args.url, args.archive, args.headless, args.timeout,
                          scroll_pause=args.scroll_pause, max_scrolls=args.max_scrolls)
        asyncio.run(rec.record())
    else:
        ap.print_help()
