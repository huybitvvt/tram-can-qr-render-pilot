"""Download the exact small model shipped in the factory-approved trial."""
from pathlib import Path
from tramcan_rapidocr.engine import prepare_models

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]/'models'/'rapidocr'
    prepare_models(root,'small')
    print('Verified PP-OCRv6 small models:',root)
