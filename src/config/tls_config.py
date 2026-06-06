"""
TLS/HTTPS Configuration
=======================

Enterprise-grade TLS configuration for secure communication.

Author: MiniMax Agent
"""

import os
import ssl
from typing import Optional, Tuple


class TLSConfig:
    """
    TLS configuration for Agent Bridge.

    Supports both development (self-signed) and production (Let's Encrypt, etc.) certificates.
    """

    def __init__(
        self,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        ca_path: Optional[str] = None,
        verify_client: bool = False,
        min_version: int = ssl.TLSVersion.TLSv1_2
    ):
        """
        Initialize TLS configuration.

        Args:
            cert_path: Path to server certificate (PEM format)
            key_path: Path to server private key (PEM format)
            ca_path: Path to CA certificate for client verification
            verify_client: Whether to verify client certificates
            min_version: Minimum TLS version (default: TLS 1.2)
        """
        self.cert_path = cert_path or os.getenv("TLS_CERT_PATH")
        self.key_path = key_path or os.getenv("TLS_KEY_PATH")
        self.ca_path = ca_path or os.getenv("TLS_CA_PATH")
        self.verify_client = verify_client or os.getenv("TLS_VERIFY_CLIENT", "false").lower() == "true"
        self.min_version = min_version

    def is_configured(self) -> bool:
        """Check if TLS is properly configured."""
        return bool(self.cert_path and self.key_path)

    def get_ssl_context(self) -> ssl.SSLContext:
        """
        Create SSL context for the server.

        Returns:
            Configured SSL context

        Raises:
            FileNotFoundError: If certificate files are missing
            ValueError: If configuration is incomplete
        """
        if not self.is_configured():
            raise ValueError(
                "TLS not configured. Set TLS_CERT_PATH and TLS_KEY_PATH environment variables "
                "or pass cert_path and key_path to constructor."
            )

        # Create SSL context
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

        # Set minimum TLS version
        context.minimum_version = self.min_version

        # Load certificate and key
        context.load_cert_chain(self.cert_path, self.key_path)

        # Optionally verify client certificates
        if self.verify_client and self.ca_path:
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(self.ca_path)
        elif self.verify_client:
            context.verify_mode = ssl.CERT_REQUIRED

        # Set secure cipher suites
        context.set_ciphers(
            "ECDHE+AESGCM:DHE+AESGCM:ECDHE+CHACHA20:DHE+CHACHA20:"
            "ECDHE+AES:DHE+AES:!aNULL:!MD5:!DSS"
        )

        return context

    def get_tls_info(self) -> dict:
        """Get TLS configuration info (without sensitive data)."""
        return {
            "enabled": self.is_configured(),
            "cert_path": self.cert_path if self.cert_path else None,
            "key_path": "***" if self.key_path else None,
            "ca_path": self.ca_path if self.ca_path else None,
            "verify_client": self.verify_client,
            "min_version": ssl.TLSVersion(self.min_version).name if hasattr(ssl.TLSVersion, self.min_version) else str(self.min_version)
        }


def create_dev_ssl_context() -> ssl.SSLContext:
    """
    Create SSL context for local development with self-signed certificates.

    WARNING: Only use for local development, not in production!

    Returns:
        SSL context configured for development
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    # For development, you can generate self-signed certs with:
    # openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

    return context


def generate_self_signed_cert(
    output_dir: str = ".",
    common_name: str = "localhost",
    organization: str = "Agent Bridge Dev"
) -> Tuple[str, str]:
    """
    Generate self-signed certificate for development.

    Args:
        output_dir: Directory to save certificates
        common_name: Common name for the certificate (usually hostname)
        organization: Organization name

    Returns:
        Tuple of (cert_path, key_path)
    """
    import subprocess
    import tempfile

    cert_path = os.path.join(output_dir, "cert.pem")
    key_path = os.path.join(output_dir, "key.pem")

    # Generate certificate using openssl
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", key_path, "-out", cert_path,
        "-days", "365", "-nodes",
        "-subj", f"/CN={common_name}/O={organization}"
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return cert_path, key_path
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to generate certificate: {e}")
    except FileNotFoundError:
        raise RuntimeError("openssl not found. Please install OpenSSL or provide pre-generated certificates.")


# Environment-based TLS configuration
def load_tls_config() -> TLSConfig:
    """
    Load TLS configuration from environment variables.

    Environment variables:
        TLS_CERT_PATH: Path to server certificate
        TLS_KEY_PATH: Path to server private key
        TLS_CA_PATH: Path to CA certificate (optional)
        TLS_VERIFY_CLIENT: Whether to verify client certs (default: false)

    Returns:
        TLSConfig instance
    """
    return TLSConfig(
        cert_path=os.getenv("TLS_CERT_PATH"),
        key_path=os.getenv("TLS_KEY_PATH"),
        ca_path=os.getenv("TLS_CA_PATH"),
        verify_client=os.getenv("TLS_VERIFY_CLIENT", "false").lower() == "true"
    )


# Production-ready SSL configuration
PRODUCTION_CIPHERS = [
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "DHE-RSA-AES128-GCM-SHA256",
    "DHE-RSA-AES256-GCM-SHA384"
]


def create_production_ssl_context(tls_config: TLSConfig) -> ssl.SSLContext:
    """
    Create production-ready SSL context.

    Args:
        tls_config: TLS configuration

    Returns:
        Production SSL context
    """
    context = tls_config.get_ssl_context()

    # Enable OCSP stapling (if supported)
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.options |= ssl.OP_NO_TLSv1
    context.options |= ssl.OP_NO_TLSv1_1
    context.options |= ssl.OP_CIPHER_SERVER_PREFERENCE

    # Set secure curves
    context.set_ecdh_curve("secp384r1")

    return context


if __name__ == "__main__":
    # Example usage
    print("TLS Configuration for Agent Bridge")
    print("=" * 50)

    # Check environment
    tls_config = load_tls_config()
    print(f"Environment TLS configured: {tls_config.is_configured()}")

    if tls_config.is_configured():
        print("\nTLS Settings:")
        info = tls_config.get_tls_info()
        for key, value in info.items():
            print(f"  {key}: {value}")
    else:
        print("\nTo enable TLS, set environment variables:")
        print("  export TLS_CERT_PATH=/path/to/cert.pem")
        print("  export TLS_KEY_PATH=/path/to/key.pem")

        print("\nFor local development, generate self-signed certs:")
        print("  python -c 'from src.config.tls_config import generate_self_signed_cert; generate_self_signed_cert()'")