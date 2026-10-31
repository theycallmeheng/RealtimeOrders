import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {validateRemoteOrigin} from './network_config.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const [action,value]=process.argv.slice(2);
try {
  if(action==='--validate') { console.log(validateRemoteOrigin(value)); }
  else if(action==='--origin' || action==='--local') {
    const profile=action==='--local' ? {mode:'local',origin:'https://localhost:3443'} : {mode:'remote',origin:validateRemoteOrigin(value)};
    const folder=path.join(root,'runtime');fs.mkdirSync(folder,{recursive:true});
    const target=path.join(folder,'network.local.json');
    if(fs.existsSync(target)) {
      const backup=path.join(folder,'backups');fs.mkdirSync(backup,{recursive:true});
      fs.copyFileSync(target,path.join(backup,'network-'+Date.now()+'.json'));
    }
    fs.writeFileSync(target+'.pending',JSON.stringify(profile,null,2)+'\n');fs.renameSync(target+'.pending',target);
    console.log(profile.origin);
  } else { throw new Error('Usage: node scripts/configure-remote.mjs --origin https://hostname | --local | --validate https://hostname'); }
} catch(error) { console.error(error.message);process.exitCode=1; }
