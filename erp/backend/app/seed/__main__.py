"""Seed CLI.

python -m app.seed base
python -m app.seed company --code 1000 --name "Örnek Sanayi A.Ş."
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app import models  # noqa: F401  (complete metadata)
from app.core.config import get_settings
from app.core.db import make_engine
from app.core.features import discover_features
from app.seed import seed_base, seed_company


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed", description="ERP başlangıç verilerini yükler."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "base", help="Yetkiler, sistem rolleri, yönetici kullanıcı, para birimleri ve ölçü birimleri"
    )
    company = commands.add_parser(
        "company", help="Şirket, işyeri, depo, Tek Düzen Hesap Planı ve muhasebe varsayılanları"
    )
    company.add_argument("--code", required=True, help="Şirket kodu (ör. 1000)")
    company.add_argument("--name", required=True, help="Şirket adı")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    # Discovery imports every feature, which registers their permissions, settings and number ranges.
    discovery = discover_features(settings.feature_list)
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as db, db.begin():
            if args.command == "base":
                default_admin = seed_base(db, discovery.permissions, admin_password=settings.admin_password)
                message = "Temel veriler yüklendi."
                if default_admin:
                    message += " Yönetici kullanıcı: admin / admin (ilk girişte parola değiştirilmelidir)."
            else:
                company = seed_company(db, code=args.code, name=args.name)
                message = f"{company.code} - {company.name} şirketi için veriler yüklendi."
    finally:
        engine.dispose()
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
