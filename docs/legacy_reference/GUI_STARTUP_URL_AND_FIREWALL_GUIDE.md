# GUI Startup URL and VM/VDI Access Guide

## Important correction

When the launcher starts the GUI with:

```text
Uvicorn running on http://0.0.0.0:8080
```

`0.0.0.0` is a server bind address. It means the server is listening on all network interfaces. It is **not** a browser URL.

Use these URLs instead:

```text
Same VM:        http://127.0.0.1:8080
Another VM/VDI: http://<Central-VM-IP>:8080
```

Example:

```text
Central VM IP: 10.20.5.10
Open from worker VM/VDI: http://10.20.5.10:8080
```

## If it works on 127.0.0.1 but not from another VM/VDI

The app is running. The issue is usually network/firewall/access.

Check on Central VM:

```powershell
netstat -ano | findstr :8080
```

Allow inbound access to port 8080 on Central VM firewall. Run PowerShell as Administrator:

```powershell
New-NetFirewallRule -DisplayName "AstraHeal AI GUI 8080" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080
```

Then test from the worker VM/VDI:

```powershell
Test-NetConnection <Central-VM-IP> -Port 8080
```

If this fails, check VM subnet routing, VPN/security group rules, and whether the worker VM can reach the Central VM IP.

## Launcher behavior in this build

The launcher now prints friendly URLs:

```text
Open on this VM: http://127.0.0.1:8080
Open from another VM/VDI using the Central VM IP, for example:
  http://10.20.5.10:8080
```

The launcher will not suggest `http://0.0.0.0:8080` as the browser URL.
