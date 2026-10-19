"""Deploy the Canada snapshot sync definitions using an already signed-in Azure CLI."""
import argparse,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--bundle",required=True)
a=p.parse_args()
b=json.loads(Path(a.bundle).read_text(encoding="utf-8-sig"))
base=f"https://management.azure.com/subscriptions/{b['subscription']}/resourceGroups/{b['resource_group']}/providers/Microsoft.DataFactory/factories/{b['factory']}"
for r in b["resources"]:
    target=Path(a.bundle).parent/(r["name"]+".json")
    target.write_text(json.dumps({"properties":r["properties"]}),encoding="utf-8")
    subprocess.run(["az","rest","--method","put","--url",f"{base}/{r['kind']}/{r['name']}?api-version=2018-06-01","--body","@"+str(target),"--output","none"],check=True)
    print("DEPLOYED",r["kind"],r["name"],flush=True)
