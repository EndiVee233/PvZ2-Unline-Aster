"""Package the A187 fixed footprint on each matching A186 baseline."""
from pathlib import Path
from zipfile import ZipFile
import argparse,hashlib,json,os,re,subprocess
from build_aster_arm64_game import copy_compressed_entry
from build_aster_save_path_fix import manifest_version

def build(apk,patch,sdk,output,signing):
    output.mkdir(parents=True,exist_ok=True);key=json.loads(signing.read_text(encoding='utf8'));report=json.loads((patch/'fixed-ranges-patch.json').read_text())
    with ZipFile(apk) as source:
        arch='ARM64' if 'assets/guest_libs/libSrc_a32.so' in source.namelist() else 'ARM32'
        native='assets/guest_libs/libSrc_a32.so' if arch=='ARM64' else 'lib/armeabi/libSrc.so'
        art='assets/reconstruction/zombie2-pvp.rsb.smf'
        assert hashlib.sha256(source.read(native)).hexdigest()==report['source_native_sha256']
        assert hashlib.sha256(source.read(art)).hexdigest()==report['source_art_sha256']
        assert hashlib.sha256(source.read('classes8.dex')).hexdigest()=='604175b2b58586ae7727c09a809e97a212244c0f2e6f7eb32900f01a21454024'
        replacements={native:(patch/'libSrc-fixed-ranges.so').read_bytes(),art:(patch/'zombie2-fixed-ranges.rsb.smf').read_bytes(),'classes8.dex':(patch/'classes8.dex').read_bytes()}
        for name,field in ((native,'native_sha256'),(art,'art_sha256'),('classes8.dex','bootstrap_sha256')):assert hashlib.sha256(replacements[name]).hexdigest()==report[field]
        manifest=source.read('AndroidManifest.xml');old='1.7.5-Unline-Aster-A186'.encode('utf-16le');temp='1.7.5-Unline-Aster-v186'.encode('utf-16le');assert manifest.count(old)==1
        replacements['AndroidManifest.xml']=manifest_version(manifest.replace(old,temp),187,186).replace('1.7.5-Unline-Aster-v187'.encode('utf-16le'),'1.7.5-Unline-Aster-A187'.encode('utf-16le'))
        unsigned=output/f'unsigned-{arch}.apk';aligned=output/f'aligned-{arch}.apk';final=output/f'PvZ2-Unline-Aster-A187-{arch}.apk'
        assert apk.resolve() not in (unsigned.resolve(),aligned.resolve(),final.resolve())
        with ZipFile(unsigned,'w') as target:
            for info in source.infolist():
                if re.fullmatch(r'META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))',info.filename,re.I):continue
                if info.filename in replacements:target.writestr(info,replacements[info.filename])
                else:copy_compressed_entry(source,info,target)
    tools=sdk/'build-tools/34.0.0';signer=['java','-jar',tools/'lib/apksigner.jar']
    subprocess.run([tools/'zipalign.exe','-p','-f','4',unsigned,aligned],check=True)
    subprocess.run([*signer,'sign','--ks',key['keystore'],'--ks-key-alias',key['alias'],'--ks-pass','env:ASTER_SIGN_PASS','--key-pass','env:ASTER_SIGN_PASS','--out',final,aligned],env=dict(os.environ,ASTER_SIGN_PASS=key['password']),check=True)
    subprocess.run([*signer,'verify',final],check=True);subprocess.run([tools/'zipalign.exe','-c','4',final],check=True,capture_output=True)
    with ZipFile(apk) as source,ZipFile(final) as target:
        for info in source.infolist():
            if info.filename in replacements or info.filename.startswith('META-INF/'):continue
            assert info.CRC==target.getinfo(info.filename).CRC,info.filename
        for name,data in replacements.items():assert target.read(name)==data,name
    record=dict(version='A187',version_code=1187,architecture=arch,apk=str(final),sha256=hashlib.file_digest(final.open('rb'),'sha256').hexdigest(),engine_sha256=report['native_sha256'],art_sha256=report['art_sha256'],bootstrap_sha256=report['bootstrap_sha256'],changed_members=list(replacements),A186_balance_preserved=True,A185_lifecycle_preserved=True,other_members_crcs_unchanged=True,runtime_accepted=False)
    (output/f'A187-{arch}-build.json').write_text(json.dumps(record,indent=2)+'\n');unsigned.unlink();aligned.unlink();print(json.dumps(record));return final

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('apk','patch','sdk','output','signing'):p.add_argument(name,type=Path)
    build(**vars(p.parse_args()))
