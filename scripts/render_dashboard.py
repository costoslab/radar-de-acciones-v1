import json

with open("dashboard_template.html", encoding="utf-8") as f:
    template = f.read()

with open("../output/dataset_compact.json", encoding="utf-8") as f:
    data_json = f.read()

# guard against premature </script> termination
data_json_safe = data_json.replace("</script>", "<\\/script>")

start_marker = "/*__DATASET_JSON__*/{}/*__END_DATASET_JSON__*/"
assert start_marker in template, "marcador no encontrado"
out = template.replace(start_marker, data_json_safe)

with open("../output/dashboard.html", "w", encoding="utf-8") as f:
    f.write(out)

import os
print("dashboard.html:", os.path.getsize("../output/dashboard.html") / 1024, "KB")
