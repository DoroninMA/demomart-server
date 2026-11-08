import sys

from .config import Settings
from .wallet_api import WalletApi, WalletError
from .wallet_payloads import class_id
from .wallet_service import WalletService


def main(api: WalletApi | None = None) -> int:
    try:
        wallet = Settings.from_env().wallet
        if not wallet.enabled:
            raise ValueError("Set WALLET_ISSUER_ID to enable Google Wallet")
        WalletService.from_settings(wallet, api).ensure_class()
    except (ValueError, OSError, WalletError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wallet class ready: {class_id(wallet)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
