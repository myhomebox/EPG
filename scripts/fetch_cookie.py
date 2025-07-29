import json
import cloudscraper
import os

def main():
    scraper = cloudscraper.create_scraper()
    resp = scraper.get("https://www.4gtv.tv/")

    cookie_dict = scraper.cookies.get_dict()

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output')
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, 'cookie.json')

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(cookie_dict, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
