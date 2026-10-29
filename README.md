# DevOps Home Lab

Home lab construit de la zero ca să înțeleg (și să pot explica) un flux GitOps complet:
**GitHub Actions → GHCR → Helm → ArgoCD → K3S**, monitorizat cu **Prometheus + Grafana**,
cu infrastructura configurată prin **Ansible** și un pipeline paralel în **Jenkins** pentru comparație.

## Arhitectură

```mermaid
flowchart LR
    dev([git push]) --> repo[GitHub repo]
    repo --> gha[GitHub Actions<br/>test + build]
    gha -->|push image| ghcr[(GHCR)]
    argocd[ArgoCD] -->|watch| repo
    argocd -->|sync Helm chart| k3s[K3S cluster]
    k3s -->|pull image| ghcr
    prom[Prometheus] -->|scrape /metrics| k3s
    grafana[Grafana] --> prom
    ansible[Ansible din WSL2] -->|SSH| vm[VM Rocky/Alma<br/>Hyper-V]
    vm --- k3s
```

## Mediu

| Rol | Ce rulează |
|---|---|
| Workstation | Windows 11 + WSL2 Ubuntu 24.04 (6 GB RAM, 4 vCPU, `networkingMode=mirrored`): Docker Engine, kubectl, Helm 4, gh, Ansible (pipx) |
| Cluster | VM Hyper-V `k3s-01`: Rocky Linux 9.8, 4 vCPU, 8 GB RAM statică, IP static `192.168.100.10` pe switch Internal + NAT, K3S v1.36.5 (canal stable), SELinux Enforcing, firewalld activ |

## Structură

| Folder | Conținut |
|---|---|
| `app/` | Aplicația (Flask/FastAPI cu `/health` și `/metrics`) + Dockerfile + teste |
| `k8s/` | Manifeste scrise de mână (Faza 4), păstrate pentru comparație cu chart-ul Helm |
| `charts/` | Chart-ul Helm al aplicației |
| `argocd/` | Manifestele `Application` pentru ArgoCD |
| `ansible/` | Inventory, playbook-uri și roluri pentru VM și K3S |
| `docs/` | `interviu.md`, `post-mortems.md`, note |

## Faze

- [x] 0. Mediul: WSL2, Hyper-V, Docker, kubectl, Helm, gh, Ansible
- [x] 1. Fundația: repo, structură, README
- [x] 2. Aplicația + Dockerfile
- [x] 3. GitHub Actions → GHCR
- [x] 4. K3S + manifeste scrise de mână
- [ ] 5. Helm chart
- [ ] 6. ArgoCD (GitOps, auto-sync, self-heal)
- [ ] 7. Monitoring (kube-prometheus-stack, ServiceMonitor, dashboard, alertă)
- [ ] 8. Ansible: provisioning VM + K3S
- [ ] 9. Jenkins (opțional)
- [ ] 10. Incidente simulate + post-mortems

## Ce am învățat

### Faza 0–1: Mediul și repo-ul
- **WSL2 ca workstation, VM separată pentru cluster.** Ansible nu rulează ca control node pe Windows, deci WSL2 e obligatoriu. Cluster-ul stă pe o VM ca să am un "server" real, accesat prin SSH.
- **`.wslconfig` limitează RAM/CPU pentru WSL2.** Fără limite, WSL poate lua până la 50% din RAM și nu-l eliberează ușor.
- **Lucrez în `~`, nu în `/mnt/c`.** `/mnt/c` trece prin 9P (lent) și nu respectă `chmod`, iar SSH refuză cheile private cu permisiuni prea largi.
- **Supply chain la instalare:** repo apt oficial cu cheie GPG (`signed-by`), checksum `sha256` pentru binarul kubectl, scriptul Helm citit înainte de rulare (nu `curl | bash`).
- **Grupul `docker` = root pe mașină.** Acceptabil în lab; în producție aș folosi rootless Docker/Podman.
- **Modificările de mediu (grupuri, `PATH`) se aplică doar în sesiuni noi.** Cauză clasică de "la mine merge, în cron/CI nu".
- **Log-urile se filtrează după `level`, nu după cuvântul "error".** La pornire, Docker loghează `level=info ... error="No such file"` la ștergerea regulilor nftables inexistente: e zgomot, nu o problemă.
- **Tokenul gh e salvat în clar** în `~/.config/gh/hosts.yml` (nu există keyring în WSL). Fișierul are 600. În producție: token cu expirare / fine-grained PAT; în CI doar `GITHUB_TOKEN` efemer.
- **Scope-ul `workflow`** e necesar ca să poți face push la fișiere din `.github/workflows/` cu un token OAuth.
- **Email noreply GitHub** în `git config`, ca adresa reală să nu apară în istoricul unui repo public.
- **Git nu urmărește foldere goale**, de aceea fiecare folder are un `.gitkeep` până primește conținut.

### Faza 2: Aplicația și imaginea Docker
- **Cardinality în Prometheus:** label-ul `path` folosește template-ul rutei, iar tot ce nu e rută (404) intră sub `unmatched`. Altfel fiecare URL random ar crea o serie nouă. Un test protejează comportamentul ăsta.
- **Trafic străin pe `localhost:8000`:** în log-uri apăreau request-uri `GET /api/state` pe care nu le-am făcut eu. Un proces de pe Windows apela portul, iar WSL2 redirecționează `localhost`. Din WSL toate conexiunile apar ca `127.0.0.1`; procesul se află din Windows cu `Get-NetTCPConnection -RemotePort 8000`.
- **`prometheus-client` ține metricile în memoria procesului:** un singur worker uvicorn per container, scalez cu `replicas`.
- **Warning-urile de deprecation contează:** `httpx` cu `TestClient` era deprecated, l-am înlocuit cu `httpx2`. Warning-ul de azi e eroarea de după următorul upgrade.
- **Layer caching:** `requirements.txt` copiat înaintea codului, deci o modificare în `main.py` nu reinstalează dependențele. Build: 19.9s la rece, 2.5s cu cache (`CACHED` la `pip install`).
- **Multi-stage build:** la această aplicație câștigul e mic (wheels precompilate), dar pattern-ul contează când apar dependențe care compilează C.
- **Non-root cu UID numeric** (`USER 10001`), pentru că `runAsNonRoot` din Kubernetes verifică doar UID numeric. Verificat cu `docker exec ... id`.
- **Exec form la `CMD`:** `docker logs` arată `Started server process [1]`, adică uvicorn e PID 1 și primește direct `SIGTERM`.
- **`PYTHONUNBUFFERED=1`:** log-urile ajung imediat la `docker logs` / `kubectl logs`.
- **Mărimea imaginii:** `DISK USAGE` 222 MB (dezarhivat, local) vs `CONTENT SIZE` 53 MB (layere comprimate, cât se transferă la push/pull).

### Faza 3: GitHub Actions
- **Triggere:** `push` pe `main` (test + build + push), `pull_request` (test + build, fără push), `workflow_dispatch` (manual). Filtrul `paths:` pornește CI doar la schimbări în `app/` sau în workflow, deci un commit de bump în `charts/` (Faza 6) nu creează o buclă.
- **`needs: test`:** nicio imagine netestată nu ajunge în registry. Fiecare job rulează pe o VM nouă, deci fiecare face propriul checkout.
- **`GITHUB_TOKEN` vs GitHub Secrets vs Kubernetes Secrets:** `GITHUB_TOKEN` e generat automat per run, expiră la final și e valabil doar pe repo-ul curent, deci nu am nevoie de PAT pentru GHCR. GitHub Secrets sunt valori pe care le adaug eu, mascate în log-uri. Kubernetes Secrets stau în etcd ca base64 (codificare, nu criptare).
- **Least privilege:** workflow-ul are `contents: read`; doar jobul `build` primește `packages: write`.
- **Scope-urile tokenului local decid ce pot face:** `gh api .../packages` a dat 403 până am adăugat `read:packages` cu `gh auth refresh`.
- **Cache pe două niveluri:** `setup-python` (cache pip, cheie = hash-ul `requirements-dev.txt`) și BuildKit `type=gha,mode=max`. La al doilea run toți pașii Docker au fost `CACHED`, pentru că se schimbase doar workflow-ul. Câștigul de timp a fost mic (56s → 50s), fiindcă imaginea e mică și timpul se duce pe setup.
- **Tag-uri imuabile:** `sha-<7 caractere>` pentru deploy, `latest` doar pe `main` și doar pentru teste manuale. `metadata-action` face numele lowercase (username-ul meu are majuscule, iar Docker cere lowercase).
- **Totul fixat, nimic flotant:** imaginea de bază, versiunile pip, action-urile (pe major; în producție pe SHA, vezi incidentul `tj-actions/changed-files`, martie 2025) și runner-ul. `ubuntu-latest` a anunțat migrarea la Ubuntu 26, așa că l-am fixat pe `ubuntu-24.04`.
- **Vizibilitatea imaginii în GHCR:** mă așteptam la `private`, dar a ieșit `public`. Pachetul publicat de un workflow cu `GITHUB_TOKEN` e legat de repo (label-ul `org.opencontainers.image.source`) și i-a moștenit vizibilitatea. K3S o poate trage fără `imagePullSecret`. Am verificat cu `gh api`, nu am presupus.
- **Secret scanning + push protection** erau deja active (default pe repo-uri publice). Am citit starea cu `gh api` înainte să modific ceva.
- **Dependabot (`.github/dependabot.yml`)** propune săptămânal upgrade-uri ca PR-uri pentru pip, imaginea de bază Docker și action-uri. Versiunile fixate nu rămân vechi, iar fiecare upgrade trece prin CI.
- **Comenzile interactive nu merg în pipe sau CI:** `gh run view | grep` fără ID a eșuat, pentru că gh nu poate afișa prompt-ul de selecție. În scripturi toți parametrii se dau explicit.

### Faza 4: VM, rețea și K3S
- **Rețea: switch Internal + NetNat, IP static.** `Default Switch` din Hyper-V schimbă subnetul la fiecare restart de Windows, ceea ce strică kubeconfig-ul și inventarul Ansible.
- **WSL nu ajungea la VM:** Windows avea `Forwarding: Disabled` pe adaptoarele vEthernet. Diagnostic pe straturi: VM-ul răspundea din Windows (`Test-NetConnection`), ruta din WSL era corectă, deci pachetul murea în Windows. Primul fix: `Set-NetIPInterface -Forwarding Enabled` pe **ambele** adaptoare (dus și întors); `ttl=63` dovedea un hop rutat. A rezistat la `wsl --shutdown`, dar **nu la restartul Windows**: adaptorul WSL e recreat la fiecare boot, iar setarea se pierde. Fix final: `networkingMode=mirrored` în `.wslconfig`. WSL folosește direct interfețele și rutele din Windows (vede `192.168.100.1` și `192.168.1.131`), deci nu mai e nevoie de forwarding (`ttl=64`, fără hop). L-am dezactivat apoi și pe adaptorul K3S-NAT. Verificat după restart real.
- **Un test de persistență trebuie să reproducă exact evenimentul de care te temi.** `wsl --shutdown` nu e același lucru cu un restart Windows.
- **Passphrase-ul cheii se cere o dată per pornire WSL**, la primul terminal: `keychain` pornește `ssh-agent`, care ține cheia decriptată doar în memorie, deci după `wsl --shutdown` sau un restart Windows se pierde. Alternativa (deblocare la primul `ssh` cu `keychain --noask` + `AddKeysToAgent yes`) există, dar am păstrat varianta actuală. Ansible (non-interactiv) are nevoie de cheia deja deblocată.
- **Exit code-ul spune stratul problemei:** `0` = port deschis, `1` = refused (nimic nu ascultă), `124` = timeout (firewall sau pachete pierdute).
- **Secure Boot pe Gen 2 cu Linux:** e nevoie de template-ul `MicrosoftUEFICertificateAuthority`, nu de cel implicit `MicrosoftWindows`.
- **ISO verificat cu SHA256**; sursa de adevăr e hash-ul, nu comentariul cu dimensiunea din fișierul CHECKSUM.
- **Checkpoint `01-clean-os`** cu VM-ul oprit, ca punct de revenire pentru Faza 8.
- **SSH:** cheie ed25519 dedicată lab-ului, cu passphrase, deblocată cu `keychain`. Fingerprint-ul host-ului se verifică out-of-band (consola Hyper-V), nu prin aceeași conexiune.
- **Hardening SSH în `sshd_config.d/10-hardening.conf`:** la `sshd` prima valoare găsită câștigă, deci `10-` bate `50-redhat.conf`. În Ansible e invers (precedența mai mare câștigă). Verific mereu configurația efectivă (`sshd -T`), validez înainte de reload (`sshd -t`) și păstrez o sesiune deschisă cât testez.
- **Swap oprit** (`swapoff` acum + `fstab` pentru boot): Kubernetes preferă un OOMKill vizibil în locul unei degradări lente pe disc.
- **firewalld rămâne activ:** 6443 (API), 80/443 (Traefik), 30000-32767 (NodePort), iar pod CIDR `10.42.0.0/16` și service CIDR `10.43.0.0/16` în zona `trusted`. Altfel DNS-ul din cluster pică fără să pomenească nicăieri de firewall.
- **K3S configurat prin `/etc/rancher/k3s/config.yaml`** (declarativ, ușor de pus în Ansible), cu `tls-san` pentru IP și hostname. Versiunea fixată pe canalul `stable`. Installer-ul a adus `k3s-selinux`, deci SELinux rămâne `Enforcing`.
- **`sudo: k3s: command not found` pe RHEL:** `secure_path` din sudoers nu conține `/usr/local/bin`, intenționat (previne PATH hijacking). Nu l-am modificat; folosesc `kubectl` din WSL.
- **kubeconfig:** copiat cu `install -m 600` (permisiuni setate atomic), contextul redenumit în `k3s-homelab`. E cheia de cluster-admin, deci nu ajunge în Git.
- **Kubernetes rulează pe containerd, nu pe Docker.** Imaginile sunt OCI, deci compatibile.
- **`helm-install-traefik` cu 1 restart:** reconciliation loop. Kubernetes nu garantează ordinea, reîncearcă până ajunge la starea dorită.
- **Deployment → ReplicaSet → Pod:** fiecare versiune de imagine are propriul ReplicaSet (baza pentru `rollout undo`). Selectorul e imuabil.
- **Readiness vs liveness:** readiness scoate pod-ul din Service, liveness repornește containerul. Verificarea DB-ului nu se pune în liveness.
- **Requests vs limits:** memory limit da, CPU limit de obicei nu (throttling). QoS `Burstable`, pentru că requests < limits.
- **Pod securityContext la nivel "restricted":** non-root, root filesystem read-only, fără capabilities, seccomp `RuntimeDefault`.
- **Service:** IP și DNS stabile peste pod-uri efemere. EndpointSlice = lista pod-urilor Ready. Load balancing-ul e aleator (3 la 1 pe 4 request-uri), nu round-robin.
- **IP-ul clientului se pierde la NodePort** (`10.42.0.1` în log-uri, SNAT). Se păstrează cu `externalTrafficPolicy: Local`.

## Greșeli făcute

- **`wsl --install` a instalat doar platforma, nu și distribuția.** După restart, `wsl -l -v` arăta "no installed distributions". Diagnostic: `wsl --version` (platforma OK), `wsl --list --online` (catalogul OK), deci lipsea doar distro-ul. Fix: `wsl --install -d Ubuntu-24.04`. Lecție: verifici fiecare componentă separat, nu doar exit code-ul installer-ului.
- **Primele comenzi le-am rulat din `/mnt/c/WINDOWS/system32`** (unde deschide WSL implicit din PowerShell admin). Am trecut în `~` înainte să apară probleme de permisiuni sau performanță.
- **`git checkout main.py` pe un fișier necomis:** după testul de cache am vrut să anulez linia adăugată, dar am primit `pathspec 'main.py' did not match any file(s) known to git`. Git poate restaura doar ce a văzut într-un commit, iar codul Fazei 2 nu era comis încă. Fix: am șters linia manual (`sed -i '$ d' main.py`). Lecție: commit des, înainte de experimente.
- **`git push` înainte de `git commit`** a răspuns `Everything up-to-date`. Push-ul trimite commit-uri, nu fișierele din staging.
- **`gh run view --log | grep` fără run ID** a eșuat cu `run or job ID required when not running interactively`. Fix: ID-ul luat cu `gh run list --json databaseId --jq '.[0].databaseId'`.
- **Am testat conectivitatea de pe VM spre el însuși** (ping la propriul IP, 0.03 ms). Testul trebuia rulat din WSL. Contează de unde pornește testul, nu doar destinația.
- **Am acceptat fingerprint-ul SSH (TOFU) fără verificare**, apoi am rulat verificarea în WSL în loc de VM. Corect: verifici în consola serverului, înainte de `yes`.
- **`scp` într-un folder inexistent (`~/.kube`)** a eșuat, dar `&&` a împiedicat `rm`-ul de pe VM. Pașii distructivi se leagă cu `&&` (sau `set -e`).
- **Am testat persistența forwarding-ului doar cu `wsl --shutdown`.** După restartul Windows, WSL nu mai ajungea la VM. Diagnostic: `Get-NetIPInterface` arăta `Forwarding: Disabled` doar pe adaptorul WSL (recreat la boot). Rezolvat cu WSL mirrored networking.
- **Comandă cu ghilimea neînchisă** a lăsat shell-ul în prompt-ul `>` (PS2). Ctrl+C și rescriere.
