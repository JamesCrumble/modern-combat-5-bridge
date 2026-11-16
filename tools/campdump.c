/* campdump: dump the campaign of a running MC5 6.0.12a (chapters -> locations (type 0 = story) -> mission nodes) via process_vm_readv; no root:
 * run as `run-as <pkg> ./campdump <pid>` on the debuggable build. Source of server/data/ah/campaign.json (documentation/protocol.md). Build: NDK clang (see tools/build_ptrace_log.sh). */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/uio.h>
static pid_t pid;
static int rd(uint64_t a, void *b, size_t n){ struct iovec l={b,n}, r={(void*)(uintptr_t)a,n}; return process_vm_readv(pid,&l,1,&r,1,0)==(ssize_t)n?0:-1; }
static uint64_t q(uint64_t a){ uint64_t v=0; rd(a,&v,8); return v; }
static uint32_t d(uint64_t a){ uint32_t v=0; rd(a,&v,4); return v; }
static void str(uint64_t a, char *out, int max){ uint8_t b0; rd(a,&b0,1); uint64_t len,data;
  if(b0&1){ len=q(a+8); data=q(a+16);} else { len=b0>>1; data=a+1; } if(len>=(uint64_t)max) len=max-1; out[0]=0; if(rd(data,out,len)==0) out[len]=0; }
int main(int c,char**v){ pid=atoi(v[1]); uint64_t base=0; char line[512]; char path[64]; snprintf(path,64,"/proc/%d/maps",pid);
  FILE*f=fopen(path,"r"); while(fgets(line,512,f)){ unsigned long long lo,off; if(strstr(line,"libMC5.so")&&sscanf(line,"%llx-%*llx %*4s %llx",&lo,&off)==2&&off==0){base=lo;break;} }
  uint64_t obj=q(q(base+0x1b9aed8)); uint64_t b=q(obj+0x30), e=q(obj+0x38);
  printf("base %llx obj %llx entries %llu\n",(unsigned long long)base,(unsigned long long)obj,(unsigned long long)((e-b)/0x48));
  for(uint64_t p=b;p<e;p+=0x48){ uint32_t ch=d(p), ty=d(p+4); uint64_t loc=q(p+8); uint32_t n=d(loc+0x80); uint64_t arr=q(loc+0x88);
    uint8_t raw[0x48]; rd(p,raw,0x48);
    printf("entry chapter=%u type=%u loc=%llx missions=%u raw=",ch,ty,(unsigned long long)loc,n); for(int i=0;i<0x48;i++) printf("%02x",raw[i]); printf("\n");
    for(uint32_t i=0;i<n && i<64;i++){ uint64_t m=q(arr+8*i); char s[64]; str(m+8,s,64); printf("  mission %s node=%u done=%u\n",s,d(m+0x38),(unsigned)(d(m+0x68)>>16&0xff)); } }
  return 0; }
