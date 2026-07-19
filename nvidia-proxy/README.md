# NVIDIA selective proxy for Hermes ywd

Hermes 不支持按 provider 设置代理。这个本地转发服务解决：

- 只有 `ywd` / NVIDIA 请求走 `127.0.0.1:7890`
- 其他模型（ycx/cpa/freemodel 等）直连，不吃全局 `HTTP_PROXY`

## Listen

- `http://127.0.0.1:18319/v1`
- systemd: `nvidia-ywd-proxy.service`

## Hermes wiring

把 `custom_providers.ywd` / `providers.ywd` 的 `base_url` 指到：

```text
http://127.0.0.1:18319/v1
```

并移除 Hermes gateway / config 全局 `HTTP_PROXY`。

## Ops

```bash
systemctl status nvidia-ywd-proxy.service
curl -sS http://127.0.0.1:18319/health
journalctl -u nvidia-ywd-proxy.service -n 50 --no-pager
```
