import argparse
import asyncio
from pathlib import Path

from src.archive import ArchiveIndex
from src.server import WaybackServer
from src.recorder import WebRecorder
from src.utils import DEFAULT_ARCHIVE, C, log


def _run_extraction(archive_dir: str, snap_id: str = None):
    """Run content extraction on one or all snapshots."""
    from src.extractor import ContentExtractor
    from src.md_generator import MarkdownGenerator

    idx = ArchiveIndex(archive_dir)

    if snap_id:
        snap_path = idx.get_snapshot_path(snap_id)
        if not snap_path:
            print(f"  {C['R']}Snapshot not found: {snap_id}{C['X']}")
            return
        targets = [(snap_id, snap_path)]
    else:
        targets = []
        for s in idx.data["snapshots"]:
            sp = idx.root / s["path"]
            targets.append((s["id"], sp))

    for sid, sp in targets:
        try:
            log("INFO", f"Extracting: {sid}")
            extractor = ContentExtractor(sp)
            data = extractor.extract()

            md_gen = MarkdownGenerator(sp / "extracted_data.json", data=data)
            md_gen.generate()

            idx.mark_extracted(sid)
            log("OK", f"Extracted: {sid} → extracted_data.json + content.md")
        except Exception as e:
            log("WARN", f"Failed to extract {sid}: {e}")

    print(f"\n  {C['G']}{C['BD']}Extraction complete!{C['X']}")
    print(f"  Processed {len(targets)} snapshot(s)\n")


def main():
    ap = argparse.ArgumentParser(
        description="WebRecorder v3 – Wayback Machine style archiver with content extraction",
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

  # Extract content from all snapshots → JSON + Markdown
  python webrecorder.py --extract-all

  # Extract a specific snapshot
  python webrecorder.py --extract books.toscrape.com_20260605_194745
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
    ap.add_argument("--extract", metavar="SNAP_ID",
                    help="Extract content from a specific snapshot → JSON + Markdown")
    ap.add_argument("--extract-all", action="store_true",
                    help="Extract content from ALL snapshots → JSON + Markdown")
    ap.add_argument("--no-extract", action="store_true",
                    help="Skip auto-extraction after recording")
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
            extracted = "✅" if idx.is_extracted(s["id"]) else "❌"
            print(f"  📸 {s['id']}  [Extracted: {extracted}]")
            print(f"     URL    : {s['url']}")
            print(f"     Assets : {s.get('asset_count', 0)}  |  API: {s.get('api_count', 0)}")
            print(f"     Time   : {s['recorded_at']}")
            print()

    elif args.extract:
        _run_extraction(args.archive, args.extract)

    elif args.extract_all:
        _run_extraction(args.archive)

    elif args.replay:
        WaybackServer(args.archive, args.port).start()

    elif args.url:
        rec = WebRecorder(args.url, args.archive, args.headless, args.timeout,
                          scroll_pause=args.scroll_pause, max_scrolls=args.max_scrolls)
        asyncio.run(rec.record())

        # Auto-extract after recording unless --no-extract is set
        if not args.no_extract:
            print(f"\n  {C['C']}Auto-extracting content...{C['X']}")
            idx = ArchiveIndex(args.archive)
            # Find the most recent snapshot (the one we just recorded)
            latest = sorted(idx.data["snapshots"],
                          key=lambda x: x["recorded_at"], reverse=True)
            if latest:
                _run_extraction(args.archive, latest[0]["id"])
    else:
        ap.print_help()
