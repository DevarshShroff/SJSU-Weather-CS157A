import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen


BASE_URL = "https://www.met.sjsu.edu/weather/sfcdata/data/"
STATION_DIRECTORIES = (
    "BlackberryHill", "CZUSoilMoisture", "DHRoof", "MtDiabloSummit",
    "MtUmunhum", "PGESanRamon", "Portable2", "SpringValley",
)
CSV_LINK = re.compile(r'href="([^"/]+\.csv)"', re.IGNORECASE)


def csv_names(url):
    with urlopen(url, timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")
    return sorted(set(CSV_LINK.findall(page)))


def download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as temporary:
        temporary_path = Path(temporary.name)
        with urlopen(url, timeout=60) as response:
            shutil.copyfileobj(response, temporary)
    temporary_path.replace(destination)


def main():
    target_root = Path(__file__).resolve().parents[1] / "data" / "raw"
    targets = [(BASE_URL, target_root, name) for name in csv_names(BASE_URL)]
    for directory in STATION_DIRECTORIES:
        url = urljoin(BASE_URL, f"{directory}/")
        targets.extend((url, target_root / directory, name) for name in csv_names(url))
    for base_url, directory, name in targets:
        print(f"Downloading {directory.name}/{name} ...", flush=True)
        download(urljoin(base_url, name), directory / name)
    print(f"Downloaded {len(targets)} CSV files to {target_root}")


if __name__ == "__main__":
    main()

