use std::fs;
use std::path::Path;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseManifest {
    pub version: String,
    pub download_url: String,
    pub sha256: String,
    pub signature_hex: String,
}

#[derive(Debug, Error)]
pub enum UpdateError {
    #[error("invalid hex encoding: {0}")]
    InvalidHex(String),
    #[error("invalid Ed25519 public key")]
    InvalidPublicKey,
    #[error("invalid Ed25519 signature")]
    InvalidSignature,
    #[error("checksum mismatch")]
    ChecksumMismatch,
    #[error("signature verification failed")]
    SignatureVerificationFailed,
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("http error: {0}")]
    Http(#[from] reqwest::Error),
}

pub fn parse_semver(version: &str) -> Option<(u64, u64, u64)> {
    let clean = version.trim().trim_start_matches('v').split('-').next()?;
    let mut parts = clean.split('.');
    let major = parts.next()?.parse::<u64>().ok()?;
    let minor = parts.next()?.parse::<u64>().ok()?;
    let patch = parts.next()?.parse::<u64>().ok()?;
    Some((major, minor, patch))
}

pub fn is_newer_version(current: &str, candidate: &str) -> bool {
    match (parse_semver(current), parse_semver(candidate)) {
        (Some(cur), Some(cand)) => cand > cur,
        _ => false,
    }
}

pub fn compute_sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

pub fn verify_sha256_hex(bytes: &[u8], expected_hex: &str) -> Result<(), UpdateError> {
    let expected = expected_hex.trim().to_ascii_lowercase();
    let actual = compute_sha256_hex(bytes);
    if actual != expected {
        return Err(UpdateError::ChecksumMismatch);
    }
    Ok(())
}

pub fn verify_ed25519_signature(
    bytes: &[u8],
    signature_hex: &str,
    pubkey_hex: &str,
) -> Result<(), UpdateError> {
    let key_bytes = hex::decode(pubkey_hex.trim())
        .map_err(|err| UpdateError::InvalidHex(err.to_string()))?;
    let key_array: [u8; 32] = key_bytes
        .try_into()
        .map_err(|_| UpdateError::InvalidPublicKey)?;
    let verifying_key = VerifyingKey::from_bytes(&key_array)
        .map_err(|_| UpdateError::InvalidPublicKey)?;

    let sig_bytes = hex::decode(signature_hex.trim())
        .map_err(|err| UpdateError::InvalidHex(err.to_string()))?;
    let sig_array: [u8; 64] = sig_bytes
        .try_into()
        .map_err(|_| UpdateError::InvalidSignature)?;
    let signature = Signature::from_bytes(&sig_array);

    verifying_key
        .verify(bytes, &signature)
        .map_err(|_| UpdateError::SignatureVerificationFailed)
}

pub fn apply_verified_update(
    current_version: &str,
    manifest: &ReleaseManifest,
    artifact_bytes: &[u8],
    pubkey_hex: &str,
    target_path: &Path,
) -> Result<bool, UpdateError> {
    if !is_newer_version(current_version, &manifest.version) {
        return Ok(false);
    }
    verify_sha256_hex(artifact_bytes, &manifest.sha256)?;
    verify_ed25519_signature(artifact_bytes, &manifest.signature_hex, pubkey_hex)?;

    let tmp_path = target_path.with_extension("new");
    fs::write(&tmp_path, artifact_bytes)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = fs::Permissions::from_mode(0o755);
        fs::set_permissions(&tmp_path, perms)?;
    }

    fs::rename(&tmp_path, target_path)?;
    Ok(true)
}

pub async fn check_and_apply_update(
    manifest_url: &str,
    pubkey_hex: &str,
    current_version: &str,
    target_path: &Path,
) -> Result<bool, UpdateError> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;
    let manifest: ReleaseManifest = client.get(manifest_url).send().await?.error_for_status()?.json().await?;
    if !is_newer_version(current_version, &manifest.version) {
        return Ok(false);
    }
    let bytes = client
        .get(&manifest.download_url)
        .send()
        .await?
        .error_for_status()?
        .bytes()
        .await?;
    apply_verified_update(current_version, &manifest, &bytes, pubkey_hex, target_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use tempfile::tempdir;

    #[test]
    fn semver_comparison_handles_v_prefix() {
        assert!(is_newer_version("0.2.0", "0.2.1"));
        assert!(is_newer_version("0.2.0", "v1.0.0"));
        assert!(!is_newer_version("0.2.0", "0.2.0"));
        assert!(!is_newer_version("0.2.0", "0.1.9"));
    }

    #[test]
    fn verifies_signed_update_and_rejects_tampering() {
        let signing_key = SigningKey::from_bytes(&[7u8; 32]);
        let pubkey_hex = hex::encode(signing_key.verifying_key().to_bytes());
        let payload = b"new-agent-binary-bytes";
        let sig_hex = hex::encode(signing_key.sign(payload).to_bytes());
        let sha256 = compute_sha256_hex(payload);

        let manifest = ReleaseManifest {
            version: "0.3.0".to_string(),
            download_url: "https://example.com/sysroar-agent".to_string(),
            sha256,
            signature_hex: sig_hex,
        };

        let dir = tempdir().unwrap();
        let bin_path = dir.path().join("sysroar-agent");
        fs::write(&bin_path, b"old-binary").unwrap();

        let tampered = apply_verified_update("0.2.0", &manifest, b"tampered-bytes", &pubkey_hex, &bin_path);
        assert!(matches!(tampered, Err(UpdateError::ChecksumMismatch)));
        assert_eq!(fs::read(&bin_path).unwrap(), b"old-binary");

        let bad_key_hex = hex::encode(SigningKey::from_bytes(&[9u8; 32]).verifying_key().to_bytes());
        let forged = apply_verified_update("0.2.0", &manifest, payload, &bad_key_hex, &bin_path);
        assert!(matches!(forged, Err(UpdateError::SignatureVerificationFailed)));

        let applied = apply_verified_update("0.2.0", &manifest, payload, &pubkey_hex, &bin_path).unwrap();
        assert!(applied);
        assert_eq!(fs::read(&bin_path).unwrap(), payload);

        let skipped = apply_verified_update("0.3.0", &manifest, payload, &pubkey_hex, &bin_path).unwrap();
        assert!(!skipped);
    }
}
