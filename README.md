# vps-mcp

**EN:** An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant operate a Linux VPS —
Docker, nginx, systemd, health checks, ports, disk/memory, firewall — through 13 narrow tools instead of a raw
shell. Every parameter that reaches a shell is validated against an allowlist pattern or quoted.

---

Servidor MCP para que un asistente de IA opere un VPS con **herramientas acotadas**, no con una terminal libre.

## Herramientas (13)

| Área | Herramientas |
|---|---|
| Docker | `docker_status`, `docker_logs`, `docker_restart` |
| nginx | `nginx_test`, `nginx_config`, `nginx_reload` (solo recarga si `nginx -t` pasa) |
| systemd | `service_status`, `service_restart`, `service_logs` |
| Salud | `health_check`, `ports`, `disk_and_memory`, `ufw_status` |

## Seguridad

Un MCP que ejecuta comandos es un riesgo en cuanto un parámetro llega a un shell. Aquí:

- Nombres de unidad y contenedor deben casar con `^[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}$`; el intervalo `since`,
  con `^\d{1,4}[smhd]?$`; `lines` se limita a 1–1000.
- `service_restart` **solo** acepta servicios de la lista configurada.
- El filtro de `nginx_config` y las URL de `health_check` pasan por `shlex.quote`.
- Una entrada inválida devuelve `REJECTED: …`; nunca llega al shell.

```text
service_logs("x; rm -rf /")   ->  REJECTED: invalid name: 'x; rm -rf /'
docker_logs("ok", since="1;id") -> REJECTED: invalid interval: '1;id'
service_restart("sshd")       ->  REJECTED: 'sshd' is not in the configured service list
```

Aun así, `run()` usa `shell=True` por las tuberías (`| head`, `| grep`): **no expongas este servidor a
entradas no confiables** y córrelo con el usuario mínimo necesario.

## Configuración

Todo es opcional, por variables de entorno:

| Variable | Qué hace |
|---|---|
| `VPS_MCP_SERVICES` | JSON `{nombre: {"port": int\|null, "path": str\|null}}` con tus servicios |
| `VPS_MCP_PUBLIC_URL` | URL pública que revisa `health_check` |
| `VPS_MCP_NGINX_SITE` | archivo de sitio de nginx para `nginx_config` |
| `VPS_MCP_CONTAINER` | contenedor por defecto de `docker_logs`/`docker_restart` |
| `VPS_MCP_PORTS` | puertos que muestra `ports` |

## Uso

```bash
pip install "mcp[cli]>=1.2,<2"
python3 server.py        # transporte stdio
```

Probado con `mcp` 1.30. La versión 2.x renombró `FastMCP` y este servidor aún no la soporta, por eso el
límite `<2`.

Regístralo en tu cliente MCP como un servidor `stdio` con ese comando.

## Licencia

MIT — ver [LICENSE](LICENSE).
