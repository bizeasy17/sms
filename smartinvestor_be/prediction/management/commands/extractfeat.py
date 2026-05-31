from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
import os
from django.conf import settings

from prediction.utils.feature_util import (
    process_and_save_features,
    read_features_from_yaml,
)


class Command(BaseCommand):
    help = "Extract features from time series data"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Time series code")
        parser.add_argument(
            "--freq", type=str, required=True, help="Frequency of the data"
        )
        parser.add_argument("--distance", type=int, help="Distance parameter")
        parser.add_argument(
            "--feattyp",
            type=str,
            help="Feature type, can be 'fields_trading' or 'feature_tech'",
        )
        parser.add_argument(
            "--trade_date",
            type=str,
            help="Trade date to extract features for",
        )
        parser.add_argument("--resume", help="Resume from previous extraction")

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        distance = options["distance"]
        feature_type = options["feattyp"]
        trade_date = options["trade_date"]
        resume = options["resume"]
        
        # if not trade_date:
        #     trade_date = datetime.today().strftime("%Y-%m-%d")

        project_root = (
            settings.BASE_DIR
            if hasattr(settings, "BASE_DIR")
            else os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        )
        feature_file_path = os.path.join(project_root, "prediction/config/features.yaml")
        fields_file_path = os.path.join(project_root, "prediction/config/fields.yaml")

        feature_type_map = {
            "tech": "fields_trading",
            "fundamental": "fields_fundamental",
            "cost": "fields_cost",
            "all": "fields_trading+fields_fundamental+fields_cost",
        }
        fields_type = feature_type_map.get(feature_type)
        if not fields_type:
            raise CommandError(f"Invalid feature type: {feature_type}")

        # fields yaml定义了trading，fundamental，cost三种特征的字段
        fields = read_features_from_yaml(fields_file_path, feature_type=fields_type)
        features = read_features_from_yaml(
            feature_file_path,
            feature_type=(
                f"feature_{feature_type}"
                if feature_type != "all"
                else "feature_tech+feature_fundamental+feature_cost"
            ),
        )

        process_and_save_features(
            ts_code=ts_code,
            freq=freq,
            distance=distance,
            fields=fields,
            feature_type=feature_type,
            features=features,
            project_root=project_root,
            trade_date=trade_date,
            resume=resume,
        )

        # self.stdout.write(f"Fields to extract: {fields}")
        # self.stdout.write(f"Features to extract: {features}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Extracting features for ts_code={ts_code}, freq={freq}, distance={distance}, resume={resume}"
            )
        )

        # TODO: Add your feature extraction logic here
