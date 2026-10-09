import os
import subprocess
import shutil
from typing import Dict, Any, List, Optional

ANDROID_JAR = os.environ.get("ANDROID_JAR", "/opt/android-sdk/platforms/android-34/android.jar")
BUILD_TOOLS = os.environ.get("BUILD_TOOLS", "/opt/android-sdk/build-tools/34.0.0")

class AndroidAPKBuilder:
    def __init__(self, work_dir: str = "/tmp/apk_build"):
        self.work_dir = work_dir
        self.aapt2 = os.path.join(BUILD_TOOLS, "aapt2")
        self.d8 = os.path.join(BUILD_TOOLS, "d8")
        self.zipalign = os.path.join(BUILD_TOOLS, "zipalign")
        self.apksigner = os.path.join(BUILD_TOOLS, "apksigner")

    def build(
        self,
        package_name: str,
        app_name: str,
        activity_code: Optional[str] = None,
        assets: Optional[List[str]] = None,
        output_apk: str = "app.apk"
    ) -> Dict[str, Any]:
        """
        Compiles and signs a real Android APK natively on Linux in < 3 seconds.
        """
        build_root = os.path.abspath(self.work_dir)
        os.makedirs(build_root, exist_ok=True)
        pkg_path = package_name.replace('.', '/')
        src_dir = os.path.join(build_root, "src", pkg_path)
        res_dir = os.path.join(build_root, "res", "values")
        assets_dir = os.path.join(build_root, "assets")
        bin_dir = os.path.join(build_root, "bin")

        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(res_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)

        # 1. AndroidManifest.xml
        manifest_path = os.path.join(build_root, "AndroidManifest.xml")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package_name}"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="34"/>
    <uses-permission android:name="android.permission.INTERNET"/>
    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW"/>
    <uses-permission android:name="android.permission.BIND_ACCESSIBILITY_SERVICE"/>
    <application android:label="{app_name}" android:hasCode="true">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>''')

        # 2. strings.xml
        with open(os.path.join(res_dir, "strings.xml"), "w", encoding="utf-8") as f:
            f.write(f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>''')

        # 3. Java Activity
        if not activity_code:
            activity_code = f'''package {package_name};
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("{app_name} - Autonomous Bot Active");
        setContentView(tv);
    }}
}}'''
        with open(os.path.join(src_dir, "MainActivity.java"), "w", encoding="utf-8") as f:
            f.write(activity_code)

        # 4. Copy Assets (e.g. JavaScript bot scripts)
        if assets:
            for a in assets:
                if os.path.exists(a):
                    shutil.copy(a, os.path.join(assets_dir, os.path.basename(a)))

        try:
            # Step 1: AAPT2 Compile
            subprocess.run([self.aapt2, "compile", "--dir", os.path.join(build_root, "res"), "-o", os.path.join(bin_dir, "res.zip")], check=True, capture_output=True)

            # Step 2: AAPT2 Link
            unaligned_apk = os.path.join(bin_dir, "unaligned.apk")
            subprocess.run([
                self.aapt2, "link",
                "-o", unaligned_apk,
                "-I", ANDROID_JAR,
                "--manifest", manifest_path,
                "--java", os.path.join(build_root, "src"),
                "-A", assets_dir,
                os.path.join(bin_dir, "res.zip"),
                "--auto-add-overlay"
            ], check=True, capture_output=True)

            # Step 3: Javac Java -> Class
            classes_dir = os.path.join(bin_dir, "classes")
            os.makedirs(classes_dir, exist_ok=True)
            subprocess.run([
                "javac", "-source", "1.8", "-target", "1.8",
                "-cp", ANDROID_JAR,
                "-d", classes_dir,
                os.path.join(src_dir, "MainActivity.java")
            ], check=True, capture_output=True)

            # Step 4: D8 Class -> DEX
            dex_dir = os.path.join(bin_dir, "dex")
            os.makedirs(dex_dir, exist_ok=True)
            class_files = []
            for root, _, files in os.walk(classes_dir):
                for f in files:
                    if f.endswith(".class"):
                        class_files.append(os.path.join(root, f))

            subprocess.run([self.d8, "--output", dex_dir, "--lib", ANDROID_JAR] + class_files, check=True, capture_output=True)

            # Step 5: Pack DEX into APK
            dex_file = os.path.join(build_root, "classes.dex")
            shutil.copy(os.path.join(dex_dir, "classes.dex"), dex_file)
            subprocess.run(["zip", "-j", unaligned_apk, dex_file], check=True, capture_output=True)

            # Step 6: Zipalign
            aligned_apk = os.path.join(bin_dir, "aligned.apk")
            subprocess.run([self.zipalign, "-f", "4", unaligned_apk, aligned_apk], check=True, capture_output=True)

            # Step 7: Create debug keystore & sign with apksigner
            keystore_path = os.path.join(build_root, "debug.keystore")
            if not os.path.exists(keystore_path):
                subprocess.run([
                    "keytool", "-genkeypair", "-keystore", keystore_path,
                    "-alias", "androiddebugkey", "-storepass", "android", "-keypass", "android",
                    "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
                    "-dname", "CN=Android Debug,O=Android,C=US"
                ], check=True, capture_output=True)

            subprocess.run([
                self.apksigner, "sign",
                "--ks", keystore_path,
                "--ks-key-alias", "androiddebugkey",
                "--ks-pass", "pass:android",
                "--key-pass", "pass:android",
                aligned_apk
            ], check=True, capture_output=True)

            # Move to target output
            final_apk = os.path.abspath(output_apk)
            os.makedirs(os.path.dirname(final_apk), exist_ok=True)
            shutil.copy(aligned_apk, final_apk)

            return {
                "success": True,
                "apk_path": final_apk,
                "size_bytes": os.path.getsize(final_apk),
                "package_name": package_name
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": f"Build error in {e.cmd}: {e.stderr.decode('utf-8', errors='replace') if e.stderr else str(e)}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
