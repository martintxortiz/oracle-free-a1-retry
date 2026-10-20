"""Retry launching one Always-Free VM.Standard.A1.Flex instance (4 OCPU / 24 GB).

All configuration comes from environment variables (GitHub Actions secrets).
Logs are public: this script never prints OCIDs, IPs or credentials.
Exit codes: 0 = instance exists or was created; 2 = still out of capacity at deadline;
1 = fatal (auth/config) error.
"""
import os, sys, time, datetime
import oci

def log(m):
    print(datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"), m, flush=True)

def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        log(f"missing required setting {name}"); sys.exit(1)
    return v

cfg = {
    "user": env("OCI_USER_OCID"),
    "tenancy": env("OCI_TENANCY_OCID"),
    "fingerprint": env("OCI_FINGERPRINT"),
    "region": env("OCI_REGION"),
    "key_content": env("OCI_PRIVATE_KEY"),
}
COMPARTMENT = os.environ.get("OCI_COMPARTMENT_OCID", "").strip() or cfg["tenancy"]
SUBNET = env("OCI_SUBNET_OCID")
IMAGE = env("OCI_IMAGE_OCID")
AD = os.environ.get("OCI_AD", "").strip()
SSH_PUB = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssh_key.pub")).read().strip()
MAX_MINUTES = float(os.environ.get("MAX_MINUTES", "50"))
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "65"))

# Fixed, Always-Free-sized shape. Do not change.
SHAPE, OCPUS, MEM_GB, BOOT_GB = "VM.Standard.A1.Flex", 4, 24, 200

try:
    oci.config.validate_config(cfg)
except Exception:
    log("invalid OCI configuration"); sys.exit(1)

cc = oci.core.ComputeClient(cfg)
idc = oci.identity.IdentityClient(cfg)

def safe_err(e):
    return f"{e.status} {e.code}"

try:
    if not AD:
        AD = idc.list_availability_domains(cfg["tenancy"]).data[0].name
    log("authenticated to Oracle OK")
except oci.exceptions.ServiceError as e:
    log(f"auth/identity error: {safe_err(e)}"); sys.exit(1)

def existing():
    return [i for i in cc.list_instances(COMPARTMENT).data
            if i.lifecycle_state not in ("TERMINATED", "TERMINATING")]

deadline = time.time() + MAX_MINUTES * 60
attempt = 0
while True:
    try:
        ex = existing()
    except oci.exceptions.ServiceError as e:
        if e.status in (401, 404):
            log(f"auth error listing instances: {safe_err(e)}"); sys.exit(1)
        log(f"list error: {safe_err(e)}"); ex = None
    if ex:
        log(f"instance exists (state {ex[0].lifecycle_state}); nothing to do"); sys.exit(0)
    if time.time() > deadline:
        log("deadline reached, still no instance; next scheduled run will retry"); sys.exit(2)
    if ex is not None:
        attempt += 1
        try:
            d = oci.core.models.LaunchInstanceDetails(
                availability_domain=AD, compartment_id=COMPARTMENT, display_name="martin-server",
                shape=SHAPE,
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=OCPUS, memory_in_gbs=MEM_GB),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    image_id=IMAGE, boot_volume_size_in_gbs=BOOT_GB, boot_volume_vpus_per_gb=10),
                create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=SUBNET, assign_public_ip=True),
                metadata={"ssh_authorized_keys": SSH_PUB})
            cc.launch_instance(d)
            log(f"attempt {attempt}: instance created"); sys.exit(0)
        except oci.exceptions.ServiceError as e:
            msg = (e.message or "").lower()
            if e.status == 429:
                log(f"attempt {attempt}: rate limited (429), backing off"); time.sleep(180); continue
            if "capacity" in msg:
                log(f"attempt {attempt}: out of capacity")
            elif e.status in (401, 403):
                log(f"attempt {attempt}: auth/permission error {safe_err(e)}"); sys.exit(1)
            elif "limit" in msg or "quota" in msg:
                log(f"attempt {attempt}: limit/quota error {safe_err(e)}; stopping"); sys.exit(1)
            else:
                log(f"attempt {attempt}: error {safe_err(e)}")
        except Exception as e:
            log(f"attempt {attempt}: unexpected {type(e).__name__}")
    time.sleep(INTERVAL)
