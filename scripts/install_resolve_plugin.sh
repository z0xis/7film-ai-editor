#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
plugin_name="com.sevenfilm.ai.editor"
source_dir="$project_dir/integrations/resolve/$plugin_name"
resolve_support="/Library/Application Support/Blackmagic Design/DaVinci Resolve"
target_root="$resolve_support/Workflow Integration Plugins"
target_dir="$target_root/$plugin_name"
native_module="$resolve_support/Developer/Workflow Integrations/Examples/SamplePlugin/WorkflowIntegration.node"

if [[ ! -f "$native_module" ]]; then
  echo "Resolve WorkflowIntegration.node bulunamadı. DaVinci Resolve Studio Developer bileşenlerini doğrulayın." >&2
  exit 1
fi

mkdir -p "$target_dir"
# Every file main.js needs at runtime. A module missing here fails at require() time, with
# the plugin simply not appearing in Resolve's menu.
for file in manifest.xml package.json main.js preload.js index.html timeline-builder.js; do
  if [[ ! -f "$source_dir/$file" ]]; then
    echo "Eklenti dosyası eksik: $file" >&2
    exit 1
  fi
  cp "$source_dir/$file" "$target_dir/$file"
done
cp "$native_module" "$target_dir/WorkflowIntegration.node"
ln -sfn "$project_dir" "$target_dir/app-root"

echo "7Film AI Editor Resolve eklentisi kuruldu:"
echo "$target_dir"
echo "DaVinci Resolve'u yeniden başlatın ve Workspace > Workflow Integrations > 7Film AI Editor menüsünü açın."

