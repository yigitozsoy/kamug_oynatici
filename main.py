"""kamug — başlatıcı.

Kullanım:  python main.py [dosya veya klasör ...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kamug.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
