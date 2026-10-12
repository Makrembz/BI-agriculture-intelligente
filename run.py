"""Point d'entrée : python run.py <commande>   (voir README.md)"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
from bi_agri.cli import main

if __name__ == "__main__":
    main()
