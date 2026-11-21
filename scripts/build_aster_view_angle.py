"""Package A184 screen message transform fixes with the accepted PVP changes."""
from pathlib import Path
from zipfile import ZipFile
import argparse,hashlib,json,os,re,subprocess
from build_aster_arm64_game import copy_compressed_entry
from build_aster_save_path_fix import manifest_version

def build(apk,native,sdk,output,signing,shim=None):
    output.mkdir(parents=True,exist_ok=True)
    key=json.loads(signing.read_text(encoding='utf8'))
    with ZipFile(apk) as source:
        arch='ARM64' if 'assets/guest_libs/libSrc_a32.so' in source.namelist() else 'ARM32'
        member='assets/guest_libs/libSrc_a32.so' if arch=='ARM64' else 'lib/armeabi/libSrc.so'
        shim_member='assets/guest_libs/libRestart_a32.so' if arch=='ARM64' else 'lib/armeabi/libRestart.so'
        replacement_shim=shim.read_bytes() if shim else None
        report=json.loads((native/'view-angle-patch.json').read_text())
        if hashlib.sha256(source.read(member)).hexdigest()!=report['source_sha256']:raise ValueError('Source engine differs from verified shared patch')
        patched=(native/'libSrc-view-angle.so').read_bytes()
        if hashlib.sha256(patched).hexdigest()!=report['sha256']:raise ValueError('Patched engine hash mismatch')
        manifest=manifest_version(source.read('AndroidManifest.xml'),184,172)
        old='1.7.5-Unline-Aster-v184'.encode('utf-16le');new='1.7.5-Unline-Aster-A184'.encode('utf-16le')
        if manifest.count(old)!=1:raise ValueError('Unknown manifest version string')
        manifest=manifest.replace(old,new)
        unsigned=output/f'unsigned-{arch}.apk';aligned=output/f'aligned-{arch}.apk';final=output/f'PvZ2-Unline-Aster-A184-{arch}.apk'
        with ZipFile(unsigned,'w') as target:
            for info in source.infolist():
                if re.fullmatch(r'META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))',info.filename,re.I):continue
                if info.filename==member:target.writestr(info,patched)
                elif info.filename==shim_member and replacement_shim is not None:target.writestr(info,replacement_shim)
                elif info.filename=='AndroidManifest.xml':target.writestr(info,manifest)
                else:copy_compressed_entry(source,info,target)
    tools=sdk/'build-tools/34.0.0'
    subprocess.run([tools/'zipalign.exe','-p','-f','4',unsigned,aligned],check=True)
    env=dict(os.environ,ASTER_SIGN_PASS=key['password'])
    signer=['java','-jar',tools/'lib/apksigner.jar']
    subprocess.run([*signer,'sign','--ks',key['keystore'],'--ks-key-alias',key['alias'],'--ks-pass','env:ASTER_SIGN_PASS','--key-pass','env:ASTER_SIGN_PASS','--out',final,aligned],env=env,check=True)
    subprocess.run([*signer,'verify',final],check=True)
    subprocess.run([tools/'zipalign.exe','-c','4',final],check=True,capture_output=True)
    with ZipFile(apk) as source,ZipFile(final) as target:
        for name in source.namelist():
            if name in (member,'AndroidManifest.xml') or (name==shim_member and replacement_shim is not None) or name.startswith('META-INF/'):continue
            # Preserve compressed game payloads and all existing JNI addresses.
            if source.getinfo(name).CRC!=target.getinfo(name).CRC:raise ValueError(f'Unexpected changed member {name}')
        if target.read(member)!=patched:raise ValueError('Packaged engine mismatch')
        if replacement_shim is not None and target.read(shim_member)!=replacement_shim:raise ValueError('Packaged shim mismatch')
        shim_hash=hashlib.sha256(target.read(shim_member)).hexdigest()
    record=dict(apk=str(final),architecture=arch,version='A184',version_code=1184,sha256=hashlib.file_digest(final.open('rb'),'sha256').hexdigest(),engine_sha256=report['sha256'],shim_sha256=shim_hash,new_signing_key=False,runtime_accepted=False)
    (output/f'A184-{arch}-build.json').write_text(json.dumps(record,indent=2)+'\n')
    # Keep the signed artifact and compact evidence, not two duplicate APKs.
    unsigned.unlink();aligned.unlink()
    print(json.dumps(record));return final

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('apk','native','sdk','output','signing'):p.add_argument(n,type=Path)
    p.add_argument('--shim',type=Path)
    build(**vars(p.parse_args()))
