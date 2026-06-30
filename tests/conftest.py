"""
Configuration pytest partagée. S'assure que les chemins d'import fonctionnent
de manière identique en local et dans le CI GitHub Actions.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
for sous_module in ["api", "ml", "nlp/extraction", "nlp/sources", "ingestion/scrapers"]:
    chemin = ROOT / sous_module
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))
