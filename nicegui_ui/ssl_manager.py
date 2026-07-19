import subprocess
import datetime
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.backends import default_backend

def ensure_tls_certs(cert_dir: Path) -> tuple[str | None, str | None]:
    """
    函数名: ensure_tls_certs
    作用: 检测并自动生成本地的自签名 TLS 证书。若证书不存在或即将过期（少于 30 天），则利用 cryptography 纯 Python 重新生成十年期证书。
    输入: 
        cert_dir (Path): 存放证书和私钥的目标目录。
    输出: 
        tuple[str | None, str | None]: 返回 (证书文件路径, 私钥文件路径)。若生成失败则返回 (None, None)。
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    cert_path = cert_dir / "server.crt"
    key_path = cert_dir / "server.key"
    san_path = cert_dir / "san.txt"
    
    needs_generation = True
    if cert_path.exists() and key_path.exists():
        try:
            cert_data = cert_path.read_bytes()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            
            # Use appropriate property depending on cryptography version
            if hasattr(cert, 'not_valid_after_utc'):
                expires_at = cert.not_valid_after_utc
                now = datetime.datetime.now(datetime.timezone.utc)
            else:
                expires_at = cert.not_valid_after
                now = datetime.datetime.utcnow()
                
            if (expires_at - now).days > 30:
                needs_generation = False
                print(f"SSL Certificate is valid until {expires_at}")
            else:
                print(f"SSL Certificate expires soon ({expires_at}), regenerating...")
        except Exception as e:
            print(f"Failed to parse existing SSL certificate: {e}")
    
    if needs_generation:
        print("Generating new SSL certificate using cryptography (Pure Python)...")
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID
        import ipaddress
        
        try:
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, u"excel-template-viz"),
            ])
            
            alt_names = [
                x509.DNSName(u"localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]
            
            # Dynamic IPs
            try:
                import socket
                hostname = socket.gethostname()
                for ip in socket.gethostbyname_ex(hostname)[2]:
                    if not ip.startswith("127."):
                        alt_names.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
            except Exception:
                pass

            # Parse san.txt if it exists
            if san_path.exists():
                san_content = san_path.read_text(encoding='utf-8').strip()
                if san_content.startswith("subjectAltName="):
                    san_content = san_content[len("subjectAltName="):]
                for item in san_content.split(','):
                    item = item.strip()
                    if item.startswith("IP:"):
                        ip_str = item[3:]
                        try:
                            ip_obj = ipaddress.IPv4Address(ip_str)
                            if not any(isinstance(x, x509.IPAddress) and x.value == ip_obj for x in alt_names):
                                alt_names.append(x509.IPAddress(ip_obj))
                        except Exception:
                            pass
                    elif item.startswith("DNS:"):
                        dns_str = item[4:]
                        if not any(isinstance(x, x509.DNSName) and x.value == dns_str for x in alt_names):
                            alt_names.append(x509.DNSName(dns_str))
            
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now_utc)
                .not_valid_after(now_utc + datetime.timedelta(days=3650))
                .add_extension(
                    x509.SubjectAlternativeName(alt_names),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256(), default_backend())
            )
            
            key_path.write_bytes(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            print("Successfully generated SSL certificate.")
            
            # Windows: 尝试自动安装到受信任的根证书颁发机构以避免 WebSocket 断连
            import sys
            if sys.platform == "win32":
                print("\n" + "="*60)
                print("检测到新生成的证书，正在尝试自动安装到受信任的根证书颁发机构。")
                print("【注意】这可能会弹出一个 Windows 安全警告，请点击“是”以允许安装。")
                print("安装后，浏览器将完全信任此服务，彻底解决 WebSocket 频繁断连 (10054) 问题。")
                print("="*60 + "\n")
                try:
                    result = subprocess.run(
                        ["certutil", "-addstore", "-user", "Root", str(cert_path)],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        print("✅ 证书已成功自动安装！")
                    else:
                        print(f"❌ 自动安装失败 (返回码 {result.returncode})。")
                        print("👉 请您手动双击打开 `certs/server.crt` -> 点击“安装证书” -> 选择“当前用户” -> 手动选择存放入“受信任的根证书颁发机构”。")
                except Exception as e:
                    print(f"❌ 自动安装出错: {e}")
                    print("👉 请您手动双击打开 `certs/server.crt`，并安装到“受信任的根证书颁发机构”。")
            else:
                print("👉 如果遇到 HTTPS 断连，请手动将 `certs/server.crt` 导入系统的受信任根证书中。")
            
            
        except Exception as e:
            print(f"WARNING: Failed to generate SSL certificate: {e}. Proceeding with HTTP.")
            return None, None
            
    return str(cert_path), str(key_path)
