"""Package A185 lifecycle changes on the matching A184 architecture baseline."""
from pathlib import Path
from zipfile import ZipFile
import argparse,hashlib,json,os,re,subprocess
from build_aster_arm64_game import copy_compressed_entry
from build_aster_save_path_fix import manifest_version

def build(apk,patch,sdk,output,signing):
    output.mkdir(parents=True,exist_ok=True)
    key=json.loads(signing.read_text(encoding='utf8'))
    report=json.loads((patch/'lifecycle-patch.json').read_text())
    dex=(patch/'classes.dex').read_bytes()
    assert hashlib.sha256(dex).hexdigest()==report['dex_sha256']
    with ZipFile(apk) as source:
        arch='ARM64' if 'assets/guest_libs/libSrc_a32.so' in source.namelist() else 'ARM32'
        member='assets/guest_libs/libSrc_a32.so' if arch=='ARM64' else 'lib/armeabi/libSrc.so'
        shim='assets/guest_libs/libRestart_a32.so' if arch=='ARM64' else 'lib/armeabi/libRestart.so'
        assert hashlib.sha256(source.read('classes.dex')).hexdigest()==report['source_dex_sha256'],'Architecture DEX baseline mismatch'
        manifest=source.read('AndroidManifest.xml');old='1.7.5-Unline-Aster-A184'.encode('utf-16le');tmp='1.7.5-Unline-Aster-v184'.encode('utf-16le')
        assert manifest.count(old)==1
        manifest=manifest_version(manifest.replace(old,tmp),185,184).replace('1.7.5-Unline-Aster-v185'.encode('utf-16le'),'1.7.5-Unline-Aster-A185'.encode('utf-16le'))
        unsigned=output/f'unsigned-{arch}.apk';aligned=output/f'aligned-{arch}.apk';final=output/f'PvZ2-Unline-Aster-A185-{arch}.apk'
        assert apk.resolve() not in (unsigned.resolve(),aligned.resolve(),final.resolve())
        with ZipFile(unsigned,'w') as target:
            for info in source.infolist():
                if re.fullmatch(r'META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))',info.filename,re.I):continue
                if info.filename=='classes.dex':target.writestr(info,dex)
                elif info.filename=='AndroidManifest.xml':target.writestr(info,manifest)
                else:copy_compressed_entry(source,info,target)
    tools=sdk/'build-tools/34.0.0';subprocess.run([tools/'zipalign.exe','-p','-f','4',unsigned,aligned],check=True)
    signer=['java','-jar',tools/'lib/apksigner.jar'];env=dict(os.environ,ASTER_SIGN_PASS=key['password'])
    subprocess.run([*signer,'sign','--ks',key['keystore'],'--ks-key-alias',key['alias'],'--ks-pass','env:ASTER_SIGN_PASS','--key-pass','env:ASTER_SIGN_PASS','--out',final,aligned],env=env,check=True)
    subprocess.run([*signer,'verify',final],check=True)
    subprocess.run([tools/'zipalign.exe','-c','4',final],check=True,capture_output=True)
    with ZipFile(apk) as source,ZipFile(final) as target:
        for info in source.infolist():
            if info.filename in ('classes.dex','AndroidManifest.xml') or info.filename.startswith('META-INF/'):continue
            assert info.CRC==target.getinfo(info.filename).CRC,info.filename
        assert target.read('classes.dex')==dex
        engine_hash=hashlib.sha256(target.read(member)).hexdigest();shim_hash=hashlib.sha256(target.read(shim)).hexdigest()
        assert engine_hash=='6fbd67f51a53ade43ba14d050ce2761ac01cbeb7ba74e2356a821275eeaa089b'
        assert shim_hash=='494205404269abd6cbc0edc29deedebee778a4512b7e879705ba0ae8a0e40901'
    result=dict(apk=str(final),architecture=arch,version='A185',version_code=1185,sha256=hashlib.file_digest(final.open('rb'),'sha256').hexdigest(),dex_sha256=report['dex_sha256'],engine_sha256=engine_hash,shim_sha256=shim_hash,unrelated_payload_crcs_preserved=True,runtime_accepted=False)
    (output/f'A185-{arch}-build.json').write_text(json.dumps(result,indent=2)+'\n')
    unsigned.unlink();aligned.unlink();print(json.dumps(result));return final

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('apk','patch','sdk','output','signing'):p.add_argument(name,type=Path)
    build(**vars(p.parse_args()))
