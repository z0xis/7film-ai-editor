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
cp "$source_dir/manifest.xml" "$target_dir/manifest.xml"
cp "$source_dir/package.json" "$target_dir/package.json"
cp "$source_dir/main.js" "$target_dir/main.js"
cp "$source_dir/preload.js" "$target_dir/preload.js"
cp "$source_dir/index.html" "$target_dir/index.html"
cp "$native_module" "$target_dir/WorkflowIntegration.node"
ln -sfn "$project_dir" "$target_dir/app-root"

echo "7Film AI Editor Resolve eklentisi kuruldu:"
echo "$target_dir"
echo "DaVinci Resolve'u yeniden başlatın ve Workspace > Workflow Integrations > 7Film AI Editor menüsünü açın."

