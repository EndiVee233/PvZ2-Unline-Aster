"""Package A186 common balance changes while preserving A185 lifecycle/bridges."""
from pathlib import Path
from zipfile import ZipFile
import argparse,hashlib,json,os,re,subprocess
from build_aster_arm64_game import copy_compressed_entry
from build_aster_save_path_fix import manifest_version

def build(apk,patch,sdk,output,signing):
    output.mkdir(parents=True,exist_ok=True);key=json.loads(signing.read_text(encoding='utf8'));evidence=json.loads((patch/'balance-patch.json').read_text())
    common={'assets/reconstruction/dynamic-original-speed.rsb.smf':('dynamic-balance.rsb.smf','resource_sha256'),
            'assets/reconstruction/aster-dynamic-rgba.plan':('aster-dynamic-rgba.plan','rgba_plan_sha256'),
            'classes8.dex':('classes8.dex','bootstrap_sha256')}
    replacements={name:(patch/file).read_bytes() for name,(file,key_name) in common.items()}
    for name,(_,key_name) in common.items():assert hashlib.sha256(replacements[name]).hexdigest()==evidence[key_name]
    with ZipFile(apk) as source:
        arch='ARM64' if 'assets/guest_libs/libSrc_a32.so' in source.namelist() else 'ARM32'
        member='assets/guest_libs/libSrc_a32.so' if arch=='ARM64' else 'lib/armeabi/libSrc.so'
        assert hashlib.sha256(source.read(member)).hexdigest()==evidence['source_native_sha256']
        assert hashlib.sha256(source.read('classes8.dex')).hexdigest()=='6ccc1d8c81877c48e47b078f44779e020692c7f98acf382145d61e457339f526'
        assert hashlib.sha256(source.read('assets/reconstruction/dynamic-original-speed.rsb.smf')).hexdigest()==evidence['source_resource_sha256']
        replacements[member]=(patch/'libSrc-balance.so').read_bytes();assert hashlib.sha256(replacements[member]).hexdigest()==evidence['native_sha256']
        old='1.7.5-Unline-Aster-A185'.encode('utf-16le');temp='1.7.5-Unline-Aster-v185'.encode('utf-16le');manifest=source.read('AndroidManifest.xml');assert manifest.count(old)==1
        replacements['AndroidManifest.xml']=manifest_version(manifest.replace(old,temp),186,185).replace('1.7.5-Unline-Aster-v186'.encode('utf-16le'),'1.7.5-Unline-Aster-A186'.encode('utf-16le'))
        unsigned=output/f'unsigned-{arch}.apk';aligned=output/f'aligned-{arch}.apk';final=output/f'PvZ2-Unline-Aster-A186-{arch}.apk'
        assert apk.resolve() not in (unsigned.resolve(),aligned.resolve(),final.resolve())
        with ZipFile(unsigned,'w') as target:
            for info in source.infolist():
                if re.fullmatch(r'META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))',info.filename,re.I):continue
                if info.filename in replacements:target.writestr(info,replacements[info.filename])
                else:copy_compressed_entry(source,info,target)
    tools=sdk/'build-tools/34.0.0';signer=['java','-jar',tools/'lib/apksigner.jar']
    subprocess.run([tools/'zipalign.exe','-p','-f','4',unsigned,aligned],check=True)
    env=dict(os.environ,ASTER_SIGN_PASS=key['password'])
    subprocess.run([*signer,'sign','--ks',key['keystore'],'--ks-key-alias',key['alias'],'--ks-pass','env:ASTER_SIGN_PASS','--key-pass','env:ASTER_SIGN_PASS','--out',final,aligned],env=env,check=True)
    subprocess.run([*signer,'verify',final],check=True);subprocess.run([tools/'zipalign.exe','-c','4',final],check=True,capture_output=True)
    with ZipFile(apk) as source,ZipFile(final) as target:
        for info in source.infolist():
            if info.filename in replacements or info.filename.startswith('META-INF/'):continue
            assert info.CRC==target.getinfo(info.filename).CRC,info.filename
        for name,data in replacements.items():assert target.read(name)==data,name
    record=dict(version='A186',version_code=1186,architecture=arch,apk=str(final),sha256=hashlib.file_digest(final.open('rb'),'sha256').hexdigest(),engine_sha256=evidence['native_sha256'],resource_sha256=evidence['resource_sha256'],rgba_plan_sha256=evidence['rgba_plan_sha256'],bootstrap_sha256=evidence['bootstrap_sha256'],changed_members=list(replacements),other_members_crcs_unchanged=True,A185_lifecycle_preserved=True,runtime_accepted=False)
    (output/f'A186-{arch}-build.json').write_text(json.dumps(record,indent=2)+'\n');unsigned.unlink();aligned.unlink();print(json.dumps(record));return final

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('apk','patch','sdk','output','signing'):p.add_argument(name,type=Path)
    build(**vars(p.parse_args()))
