"""Container identity and persistent-volume configuration tests."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_container_uses_configurable_non_root_identity():
    dockerfile = (ROOT / "Dockerfile").read_text()
    entrypoint = (ROOT / "scripts/entrypoint.sh").read_text()

    assert "ARG PUID=1000" in dockerfile
    assert "ARG PGID=1000" in dockerfile
    assert "ENV PUID=1000" in dockerfile
    assert "PGID=1000" in dockerfile
    assert 'exec gosu "${PUID}:${PGID}"' in entrypoint
    assert 'chown -R "${PUID}:${PGID}" "${CONFIG_DIR}"' in entrypoint
    assert "USER mediafinder" not in dockerfile
    assert "999" not in dockerfile
    assert "999" not in entrypoint


def test_compose_and_environment_defaults_follow_home_server_pattern():
    compose = (ROOT / "docker-compose.example.yml").read_text()
    env_example = (ROOT / ".env.example").read_text()

    assert "PUID: ${PUID:-1000}" in compose
    assert "PGID: ${PGID:-1000}" in compose
    assert "PUID=1000" in env_example
    assert "PGID=1000" in env_example
