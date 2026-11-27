"""kamug-export.exe girişi (PyInstaller): pencere açmadan dışa aktarma, bkz. kamug/export.py."""
import sys

from kamug.export import main

if __name__ == "__main__":
    sys.exit(main())
