import os
import shutil
import json
import uuid
import zipfile
import re
import codecs
import tempfile
from flask import Flask, render_template, request, send_file

app = Flask(__name__)

# --- ระบบคลาสเพื่อแยกข้อมูลของแต่ละ Request ---
class AddonMerger:
    def __init__(self, base_temp_dir):
        self.script_entry_points = []
        self.final_dependencies = {}
        self.highest_min_engine = [1, 21, 0]
        self.TEXTURE_DEFINITIONS = ["item_texture.json", "terrain_texture.json", "blocks.json"]
        
        # ตั้งค่าโฟลเดอร์ทำงานชั่วคราว
        self.temp_folder = os.path.join(base_temp_dir, "temp_extracted")
        self.workplace_folder = os.path.join(base_temp_dir, "merged_workplace")
        self.rp_work_dir = os.path.join(self.workplace_folder, "RP_Files")
        self.bp_work_dir = os.path.join(self.workplace_folder, "BP_Files")
        
        os.makedirs(self.temp_folder, exist_ok=True)
        os.makedirs(self.rp_work_dir, exist_ok=True)
        os.makedirs(self.bp_work_dir, exist_ok=True)

    def remove_comments(self, json_str):
        pattern = r'//.*?$|/\*.*?\*/'
        return re.sub(pattern, '', json_str, flags=re.MULTILINE|re.DOTALL)

    def remove_trailing_commas(self, json_str):
        json_str = re.sub(r',\s*\}', '}', json_str)
        json_str = re.sub(r',\s*\]', ']', json_str)
        return json_str

    def load_json_robust(self, path):
        content = ""
        encodings = ['utf-8-sig', 'utf-8', 'latin-1']
        for enc in encodings:
            try:
                with open(path, 'r', encoding=enc) as f:
                    content = f.read()
                start_index = content.find('{')
                if start_index != -1:
                    content = content[start_index:]
                break
            except:
                continue
        if not content: return None
        try:
            content = self.remove_comments(content)
            content = self.remove_trailing_commas(content)
            return json.loads(content)
        except:
            return None

    def extract_recursive(self, file_path, extract_to):
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            for root, dirs, files in os.walk(extract_to):
                for file in files:
                    if file.lower().endswith(('.mcaddon', '.mcpack', '.zip')):
                        nested_archive = os.path.join(root, file)
                        nested_extract_to = os.path.join(root, os.path.splitext(file)[0])
                        self.extract_recursive(nested_archive, nested_extract_to)
                        os.remove(nested_archive)
            return True
        except Exception as e:
            return False

    def merge_texture_definitions(self, src_path, dst_path):
        try:
            src_data = self.load_json_robust(src_path)
            if not os.path.exists(dst_path):
                with open(dst_path, 'w', encoding='utf-8') as f:
                    json.dump(src_data, f, indent=4)
                return

            dst_data = self.load_json_robust(dst_path)
            if not src_data or not dst_data: return

            if "texture_data" in src_data:
                if "texture_data" not in dst_data:
                    dst_data["texture_data"] = {}
                for key, val in src_data["texture_data"].items():
                    if key not in dst_data["texture_data"]:
                        dst_data["texture_data"][key] = val
                    else:
                        if "textures" in val:
                            dst_data["texture_data"][key] = val 

            if "resource_pack_name" in src_data:
                 dst_data["resource_pack_name"] = "Merged Resources"

            with open(dst_path, 'w', encoding='utf-8') as f:
                json.dump(dst_data, f, indent=4)
        except:
            pass

    def deep_merge(self, dict1, dict2):
        if isinstance(dict1, dict) and isinstance(dict2, dict):
            for key, value in dict2.items():
                if key not in dict1:
                    dict1[key] = value
                else:
                    dict1[key] = self.deep_merge(dict1[key], value)
            return dict1
        elif isinstance(dict1, list) and isinstance(dict2, list):
            if not dict1: return dict2
            if not dict2: return dict1
            if isinstance(dict1[0], (int, float)): return dict2 
            try:
                if isinstance(dict1[0], str):
                    return list(set(dict1 + dict2))
            except:
                return dict1 + dict2
            return dict1 + dict2
        else:
            return dict2

    def patch_js_content(self, content, filename):
        def fix_path_match(match):
            full_match = match.group(0)
            keyword = match.group(1)
            quote = match.group(2)
            path = match.group(3)
            if path.startswith("@") or path.startswith("."): return full_match
            if path.startswith("scripts/"):
                new_path = "./" + path.replace("scripts/", "")
                return f'{keyword} {quote}{new_path}{quote}'
            return f'{keyword} {quote}./{path}{quote}'

        content = re.sub(r'(import)\s+([\"\'])(.*?)([\"\'])', fix_path_match, content)
        content = re.sub(r'(from)\s+([\"\'])(.*?)([\"\'])', fix_path_match, content)
        
        if "world.events.tick.subscribe" in content:
            if '@minecraft/server"' in content:
                if "system" not in content.split('@minecraft/server"')[0]:
                     content = content.replace('@minecraft/server";', '@minecraft/server"; import { system as _sys_shim } from "@minecraft/server";')
            else:
                 content = 'import { system as _sys_shim } from "@minecraft/server";\n' + content
            content = content.replace("world.events.tick.subscribe", "_sys_shim.runInterval")
        return content

    def merge_directories(self, src, dst, is_bp=False):
        if not os.path.exists(dst): os.makedirs(dst)
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if item == "manifest.json": continue 
            if os.path.isdir(s):
                if is_bp and item == "scripts": continue 
                self.merge_directories(s, d, is_bp)
            else:
                if item.endswith(".js") and is_bp: continue
                if item in self.TEXTURE_DEFINITIONS:
                    self.merge_texture_definitions(s, d)
                    continue

                if not os.path.exists(d): shutil.copy2(s, d)
                else:
                    if item.endswith(".lang"): 
                        try:
                            with codecs.open(s, 'r', encoding='utf-8-sig') as f: lines = f.readlines()
                            with codecs.open(d, 'a', encoding='utf-8') as f:
                                f.write("\n")
                                for l in lines: f.write(l.replace('\ufeff',''))
                        except: pass
                    elif item.endswith(".json"):
                        try:
                            src_d = self.load_json_robust(s)
                            dst_d = self.load_json_robust(d)
                            if src_d and dst_d:
                                merged = self.deep_merge(dst_d, src_d)
                                with open(d, 'w', encoding='utf-8') as f: json.dump(merged, f, indent=4)
                            else: shutil.copy2(s, d)
                        except: shutil.copy2(s, d)
                    else: shutil.copy2(s, d)

    def find_pack_type(self, folder_path):
        manifest_path = os.path.join(folder_path, "manifest.json")
        if os.path.exists(manifest_path):
            data = self.load_json_robust(manifest_path)
            if data:
                for module in data.get("modules", []):
                    m_type = module.get("type", "")
                    if m_type in ["resources", "data", "client_data", "skin_pack", "world_template"]:
                        return m_type
        return None

    def process_manifest(self, manifest_path, current_pack_root, target_bp_dir):
        data = self.load_json_robust(manifest_path)
        if not data: return

        for dep in data.get("dependencies", []):
            if "module_name" in dep:
                mod_name = dep["module_name"]
                if mod_name not in self.final_dependencies:
                    self.final_dependencies[mod_name] = dep
            elif "uuid" in dep:
                self.final_dependencies[f"uuid_{dep['uuid']}"] = dep

        for mod in data.get("modules", []):
            if mod.get("type") in ["script", "javascript"]:
                entry_point = mod.get("entry", "")
                if entry_point:
                    possible_paths = [entry_point]
                    if entry_point.startswith("scripts/"):
                        possible_paths.append(entry_point.replace("scripts/", ""))
                    else:
                        possible_paths.append(f"scripts/{entry_point}")
                    
                    src_script_path = None
                    script_root_dir = ""
                    
                    for p in possible_paths:
                        p_os = p.replace("/", os.sep)
                        check_path = os.path.join(current_pack_root, p_os)
                        if os.path.exists(check_path):
                            src_script_path = check_path
                            if "scripts" in p:
                                script_root_dir = "scripts"
                            else:
                                script_root_dir = os.path.dirname(p)
                            break
                    
                    if src_script_path:
                        full_src_dir = os.path.join(current_pack_root, script_root_dir) if script_root_dir else current_pack_root
                        unique_id = str(uuid.uuid4())[:8]
                        isolated_folder_name = f"sub_{unique_id}"
                        target_isolated_path = os.path.join(target_bp_dir, "scripts", isolated_folder_name)
                        
                        if not os.path.exists(target_isolated_path):
                            os.makedirs(target_isolated_path)

                        for root, dirs, files in os.walk(full_src_dir):
                            for file in files:
                                s = os.path.join(root, file)
                                rel = os.path.relpath(s, full_src_dir)
                                d = os.path.join(target_isolated_path, rel)
                                os.makedirs(os.path.dirname(d), exist_ok=True)
                                
                                if file.endswith(".js"):
                                    try:
                                        with codecs.open(s, 'r', encoding='utf-8') as f: content = f.read()
                                        new_content = self.patch_js_content(content, file)
                                        with codecs.open(d, 'w', encoding='utf-8') as f: f.write(new_content)
                                    except:
                                        shutil.copy2(s, d)
                                else:
                                    shutil.copy2(s, d)

                        rel_entry = os.path.relpath(src_script_path, full_src_dir)
                        final_rel_path = f"scripts/{isolated_folder_name}/{rel_entry}".replace("\\", "/")
                        
                        if "md" in final_rel_path or "main" in final_rel_path:
                            self.script_entry_points.insert(0, final_rel_path)
                        else:
                            self.script_entry_points.append(final_rel_path)

        header = data.get("header", {})
        ver = header.get("min_engine_version", [1, 13, 0])
        if ver[1] >= 21: self.highest_min_engine = [1, 21, 0]
        elif ver > self.highest_min_engine: self.highest_min_engine = ver

    def create_master_loader(self, target_bp_dir):
        if not self.script_entry_points: return None
        scripts_dir = os.path.join(target_bp_dir, "scripts")
        if not os.path.exists(scripts_dir): os.makedirs(scripts_dir)
        master_path = os.path.join(scripts_dir, "merged_master_loader.js")

        with open(master_path, 'w', encoding='utf-8') as f:
            f.write("// V54 Async Master Loader\n")
            f.write("async function loadScripts() {\n")
            for entry in self.script_entry_points:
                rel = "./" + entry[8:] if entry.startswith("scripts/") else "../" + entry
                f.write(f'    try {{ await import("{rel}"); console.log("Loaded: {rel}"); }} catch (e) {{ console.warn("Failed to load: {rel}", e); }}\n')
            f.write("}\n")
            f.write("loadScripts();\n")
        return "scripts/merged_master_loader.js"

    # --- เพิ่มพารามิเตอร์ custom_name ตรงนี้ ---
    def create_final_manifest(self, folder_path, pack_type, description, custom_name):
        module_type = "resources" if pack_type == "RP" else "data"
        all_modules = [{"type": module_type, "uuid": str(uuid.uuid4()), "version": [1, 0, 0]}]
        
        if pack_type == "BP" and self.script_entry_points:
            master = self.create_master_loader(folder_path)
            if master:
                all_modules.append({
                    "type": "script",
                    "language": "javascript",
                    "uuid": str(uuid.uuid4()),
                    "version": [1, 0, 0],
                    "entry": master
                })

        self.final_dependencies["@minecraft/server"] = {"module_name": "@minecraft/server", "version": "1.19.0"}
        self.final_dependencies["@minecraft/server-ui"] = {"module_name": "@minecraft/server-ui", "version": "1.3.0"}

        manifest = {
            "format_version": 2,
            "header": {
                # เปลี่ยนชื่อที่นี่ ให้เอา custom_name มาแสดง ตามด้วย (RP) หรือ (BP)
                "name": f"{custom_name} ({pack_type})",
                "description": description,
                "uuid": str(uuid.uuid4()),
                "version": [1, 0, 0],
                "min_engine_version": self.highest_min_engine
            },
            "modules": all_modules,
            "dependencies": list(self.final_dependencies.values())
        }
        with open(os.path.join(folder_path, "manifest.json"), 'w') as f:
            json.dump(manifest, f, indent=4)

    def zip_folder(self, folder_path, output_path):
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, folder_path)
                    zf.write(file_path, arcname)


# --- ส่วนจัดการ Web Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/merge', methods=['POST'])
def merge_addons():
    uploaded_files = request.files.getlist("files")
    
    # 1. จัดการชื่อไฟล์และชื่อแอดออน
    raw_name = request.form.get("output_name", "Merged_Addon").strip()
    base_name = raw_name.replace(".mcaddon", "") # ชื่อเพียวๆ เอาไว้ตั้งชื่อแอดออนในเกม
    output_name = base_name + ".mcaddon"         # ชื่อไฟล์สำหรับให้โหลด

    if not uploaded_files or uploaded_files[0].filename == '':
        return "ไม่มีการเลือกไฟล์", 400

    temp_dir = tempfile.mkdtemp()
    
    try:
        input_folder = os.path.join(temp_dir, "input")
        os.makedirs(input_folder)
        for file in uploaded_files:
            if file.filename:
                file.save(os.path.join(input_folder, file.filename))

        merger = AddonMerger(temp_dir)
        
        for filename in os.listdir(input_folder):
            file_path = os.path.join(input_folder, filename)
            current_temp = os.path.join(merger.temp_folder, os.path.splitext(filename)[0])
            os.makedirs(current_temp, exist_ok=True)
            
            if merger.extract_recursive(file_path, current_temp):
                for root, dirs, files in os.walk(current_temp):
                    if "manifest.json" in files:
                        pack_type = merger.find_pack_type(root)
                        if pack_type:
                            manifest_path = os.path.join(root, "manifest.json")
                            if pack_type in ["resources", "skin_pack"]: 
                                merger.merge_directories(root, merger.rp_work_dir, is_bp=False)
                            elif pack_type in ["data", "client_data", "world_template"]:
                                merger.process_manifest(manifest_path, root, merger.bp_work_dir)
                                merger.merge_directories(root, merger.bp_work_dir, is_bp=True)
                        else:
                            if "RP" in root or "Resource" in root:
                                merger.merge_directories(root, merger.rp_work_dir, is_bp=False)
                            elif "BP" in root or "Behavior" in root:
                                merger.process_manifest(os.path.join(root, "manifest.json"), root, merger.bp_work_dir)
                                merger.merge_directories(root, merger.bp_work_dir, is_bp=True)

        # 3. สร้างไฟล์แพ็กที่สมบูรณ์ โดยส่ง base_name เข้าไปด้วย
        pack_list = []
        if os.path.exists(merger.rp_work_dir) and os.listdir(merger.rp_work_dir):
            merger.create_final_manifest(merger.rp_work_dir, "RP", "Merged Resource Pack", base_name)
            rp_pack_path = os.path.join(temp_dir, "Merged_RP.mcpack")
            merger.zip_folder(merger.rp_work_dir, rp_pack_path)
            pack_list.append(rp_pack_path)
            
        if os.path.exists(merger.bp_work_dir) and os.listdir(merger.bp_work_dir):
            merger.create_final_manifest(merger.bp_work_dir, "BP", "Merged Behavior Pack", base_name)
            bp_pack_path = os.path.join(temp_dir, "Merged_BP.mcpack")
            merger.zip_folder(merger.bp_work_dir, bp_pack_path)
            pack_list.append(bp_pack_path)

        final_file_path = os.path.join(temp_dir, output_name)
        if pack_list:
            with zipfile.ZipFile(final_file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for pack in pack_list: 
                    zf.write(pack, os.path.basename(pack))
            
            return send_file(final_file_path, as_attachment=True, download_name=output_name)
        else:
            return "ไม่พบข้อมูล Addon ที่สามารถรวมได้", 400

    except Exception as e:
        return f"เกิดข้อผิดพลาดในการประมวลผล: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)