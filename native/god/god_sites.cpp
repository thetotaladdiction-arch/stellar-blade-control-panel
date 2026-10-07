#include "god_sites.hpp"

#include <array>
#include <cstdio>
#include <cstring>

#include <windows.h>

namespace sbgod::sites
{
    namespace
    {
        // ---- Hook entry windows (exact bytes from the certified exe) ------

        // SetActorStat 0x1A684F0: 16-byte patch = mov [rsp+8],rbx / mov [rsp+10h],rbp /
        // mov [rsp+18h],rsi / push rdi. The window runs through the Stat[] write
        // `movss [rbx+rdi*4+118h], xmm0` at +0x2B (rbx = actor, rdi = stat type).
        constexpr std::uint8_t kSetActorStatWindow[] = {
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C, 0x24, 0x10, 0x48, 0x89, 0x74, 0x24, 0x18, 0x57,
            0x48, 0x83, 0xEC, 0x20, 0x48, 0x63, 0xFA, 0x48, 0x8B, 0xD9, 0x8B, 0xCF, 0x0F, 0x28, 0xCA, 0x41,
            0x0F, 0xB6, 0xF1, 0xE8, 0x08, 0xF1, 0x20, 0x00, 0x8D, 0x47, 0xFD, 0xF3, 0x0F, 0x11, 0x84, 0xBB,
            0x18, 0x01, 0x00, 0x00,
        };
        // ApplyStatExecute 0x1B1F620: 14-byte patch = push rbp/rsi/rdi/r15, lea rbp,[rsp-0F8h].
        // The window runs through `mov rsi, rcx` ... `mov edx, [rsi+10h]` (ActorGUID).
        constexpr std::uint8_t kApplyStatExecuteWindow[] = {
            0x40, 0x55, 0x56, 0x57, 0x41, 0x57, 0x48, 0x8D, 0xAC, 0x24, 0x08, 0xFF, 0xFF, 0xFF, 0x48, 0x81,
            0xEC, 0xF8, 0x01, 0x00, 0x00, 0x48, 0x8B, 0x05, 0x04, 0x61, 0x20, 0x05, 0x48, 0x33, 0xC4, 0x48,
            0x89, 0x85, 0xB0, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xF1, 0xE8, 0xF2, 0x85, 0xF7, 0xFF, 0x8B, 0x56,
            0x10,
        };
        // DeadExecute 0x1B1FFF0: 15-byte patch = push rbp/rbx/r13/r15, lea rbp,[rsp-0C8h].
        constexpr std::uint8_t kDeadExecuteWindow[] = {
            0x40, 0x55, 0x53, 0x41, 0x55, 0x41, 0x57, 0x48, 0x8D, 0xAC, 0x24, 0x38, 0xFF, 0xFF, 0xFF, 0x48,
            0x81, 0xEC, 0xC8, 0x01, 0x00, 0x00, 0x48, 0x8B, 0x05, 0x33, 0x57, 0x20, 0x05, 0x48, 0x33, 0xC4,
            0x48, 0x89, 0x85, 0xB0, 0x00, 0x00, 0x00, 0x4C, 0x8B, 0xF9, 0xE8, 0x21, 0x7C, 0xF7, 0xFF, 0x41,
            0x8B, 0x57, 0x10,
        };
        // DeathTransition 0x1A6ED60: 18-byte patch = mov rax,rsp + seven pushes + lea rbp,[rsp-50h].
        // RAX carries the entry RSP into the body, so the trampoline jumps back via R11.
        constexpr std::uint8_t kDeathTransitionWindow[] = {
            0x48, 0x8B, 0xC4, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x56, 0x41, 0x57, 0x48, 0x8D, 0x6C,
            0x24, 0xB0, 0x48, 0x81, 0xEC, 0x50, 0x01, 0x00, 0x00, 0x0F, 0x29, 0x70, 0xA8, 0x0F, 0x29, 0x78,
            0x98,
        };
        // ActorStateChange 0x1A638C0: 20-byte patch = mov [rsp+20h],rbx / mov [rsp+10h],edx /
        // push rbp/rsi/r14 / sub rsp,70h / movsxd rbx,edx.
        constexpr std::uint8_t kActorStateChangeWindow[] = {
            0x48, 0x89, 0x5C, 0x24, 0x20, 0x89, 0x54, 0x24, 0x10, 0x55, 0x56, 0x41, 0x56, 0x48, 0x83, 0xEC,
            0x70, 0x48, 0x63, 0xDA, 0x41, 0x0F, 0xB6, 0xF1, 0x41, 0x0F, 0xB6, 0xE8, 0x4C, 0x8B, 0xF1, 0x45,
            0x84, 0xC9, 0x75, 0x12,
        };
        // v1.3.1 ApplyStatDiff 0x1A64CE0: 14-byte patch = mov rax,rsp + five pushes +
        // lea rbp,[rax-47h]. RAX carries the entry RSP into the body (movaps
        // [rax-38h]), so the trampoline jumps back via R11. The window runs
        // through mov rbx,r8 (ctx) / cvtss2sd xmm0,xmm3 (diff) / movsxd r15,edx
        // (stat) / mov rsi,rcx (actor): the argument registers the hook reads.
        constexpr std::uint8_t kApplyStatDiffWindow[] = {
            0x48, 0x8B, 0xC4, 0x55, 0x53, 0x56, 0x41, 0x54, 0x41, 0x57, 0x48, 0x8D, 0x68, 0xB9, 0x48, 0x81,
            0xEC, 0x00, 0x01, 0x00, 0x00, 0x0F, 0x57, 0xC0, 0x0F, 0x29, 0x70, 0xC8, 0x0F, 0x29, 0x78, 0xB8,
            0x49, 0x8B, 0xD8, 0xF3, 0x0F, 0x5A, 0xC3, 0x4C, 0x63, 0xFA, 0x48, 0x8B, 0xF1,
        };

        // ---- Semantic anchors -------------------------------------------

        // [0x1B1F957,0x1B1F96A): movss xmm2,[rsi+24h] / xor r9d,r9d / mov edx,[rsi+14h] /
        // mov rcx,r15 / call SetActorStat.  rsi = FSBActorApplyStat, r15 = actor
        // looked up by [rsi+10h]. Return address 0x1B1F96A.
        constexpr std::uint8_t kApplyStatSetterCall[] = {
            0xF3, 0x0F, 0x10, 0x56, 0x24, 0x45, 0x33, 0xC9, 0x8B, 0x56, 0x14, 0x49, 0x8B, 0xCF, 0xE8, 0x86,
            0x8B, 0xF4, 0xFF,
        };
        // [0x1B1F7FC,0x1B1F83E): the apply-diff call and the Stat[] compare
        // `movss xmm8,[r15+rax*4+118h]` / `ucomiss xmm8,[rsi+24h]`.
        constexpr std::uint8_t kApplyStatDiffCall[] = {
            0x8B, 0x46, 0x20, 0x4C, 0x8B, 0xC7, 0xF3, 0x0F, 0x10, 0x5E, 0x18, 0x49, 0x8B, 0xCF, 0x8B, 0x56,
            0x14, 0x89, 0x44, 0x24, 0x30, 0x0F, 0xB6, 0x46, 0x1D, 0x88, 0x44, 0x24, 0x28, 0x0F, 0xB6, 0x46,
            0x1C, 0x88, 0x44, 0x24, 0x20, 0x48, 0x89, 0x7C, 0x24, 0x70, 0xE8, 0xB5, 0x54, 0xF4, 0xFF, 0x48,
            0x63, 0x46, 0x14, 0xF3, 0x45, 0x0F, 0x10, 0x84, 0x87, 0x18, 0x01, 0x00, 0x00, 0x44, 0x0F, 0x2E,
            0x46, 0x24,
        };
        // [0x1B20167,0x1B201BF): DeathTransition(r13, [r15+14h], [r15+18h], [r15+1Ch],
        // out, [r15+20h], out, 0, 0, [r15+24h], [r15+25h]); r15 = FSBActorDead.
        constexpr std::uint8_t kDeadExecuteFieldsCall[] = {
            0x41, 0x0F, 0xB6, 0x47, 0x25, 0x49, 0x8B, 0xCD, 0x45, 0x8B, 0x4F, 0x1C, 0x45, 0x8B, 0x47, 0x18,
            0x41, 0x8B, 0x57, 0x14, 0x88, 0x44, 0x24, 0x50, 0x41, 0x0F, 0xB6, 0x47, 0x24, 0x88, 0x44, 0x24,
            0x48, 0x48, 0x8B, 0xC3, 0x48, 0x89, 0x5C, 0x24, 0x40, 0x48, 0x8D, 0x44, 0x24, 0x60, 0x88, 0x5C,
            0x24, 0x38, 0x48, 0x89, 0x44, 0x24, 0x30, 0x41, 0x8B, 0x47, 0x20, 0x89, 0x44, 0x24, 0x28, 0x48,
            0x8D, 0x44, 0x24, 0x70, 0x48, 0x89, 0x44, 0x24, 0x20, 0x48, 0x89, 0x5C, 0x24, 0x70, 0x48, 0x89,
            0x5C, 0x24, 0x60, 0xE8, 0xA1, 0xEB, 0xF4, 0xFF,
        };
        // [0x1BAE8A3,0x1BAE8B1): mov rcx,[r13+60h] / mov [rsp+20h],rax / call DeathTransition.
        constexpr std::uint8_t kDeadLocalCall[] = {
            0x49, 0x8B, 0x4D, 0x60, 0x48, 0x89, 0x44, 0x24, 0x20, 0xE8, 0xAF, 0x04, 0xEC, 0xFF,
        };
        // [0x1BADEBF,0x1BADED5): xor r9d,r9d / movzx r8d,dil / mov edx,r15d /
        // mov rcx,rbx / movzx r12d,al / call ActorStateChange.
        constexpr std::uint8_t kStateScopedCall[] = {
            0x45, 0x33, 0xC9, 0x44, 0x0F, 0xB6, 0xC7, 0x41, 0x8B, 0xD7, 0x48, 0x8B, 0xCB, 0x44, 0x0F, 0xB6,
            0xE0, 0xE8, 0xEB, 0x59, 0xEB, 0xFF,
        };
        // [0xE36F9B,0xE36FA1): mov [rip+disp32], eax -> GGameThreadId 0x706B538.
        constexpr std::uint8_t kGameThreadIdInit[] = {0x89, 0x05, 0x97, 0x45, 0x23, 0x06};

        // ---- v1.1.1 player-identity chain -------------------------------

        // [0x1A97C44,0x1A97C50): local-client getter fast path
        // `mov rax,[rip+559A925h]` (-> cache 0x7032570) / test rax,rax / jnz.
        // The identity pass reads this cache; it never calls the lazy getter.
        constexpr std::uint8_t kLocalClientCacheLoad[] = {
            0x48, 0x8B, 0x05, 0x25, 0xA9, 0x59, 0x05, 0x48, 0x85, 0xC0, 0x75, 0x4C,
        };
        // [0x1CC2590,0x1CC25DA): whole CurrentTargetGuid (the function
        // SBLiveAddNative v0.3.1 calls live on this build): client+0xC8 holder,
        // index [+0x3C] < count [+0x30], entry = [[+0x28]+index*8],
        // return (entry+0x10)->vtable[+0x38]().
        constexpr std::uint8_t kCurrentTargetGuid[] = {
            0x48, 0x83, 0xEC, 0x28, 0xE8, 0xA7, 0x56, 0xDD, 0xFF, 0x48, 0x8B, 0x80, 0xC8, 0x00, 0x00, 0x00,
            0x48, 0x85, 0xC0, 0x74, 0x2E, 0x48, 0x63, 0x48, 0x3C, 0x85, 0xC9, 0x78, 0x0F, 0x3B, 0x48, 0x30,
            0x7D, 0x0A, 0x48, 0x8B, 0x40, 0x28, 0x48, 0x8B, 0x0C, 0xC8, 0xEB, 0x02, 0x33, 0xC9, 0x48, 0x85,
            0xC9, 0x74, 0x10, 0x48, 0x8B, 0x41, 0x10, 0x48, 0x83, 0xC1, 0x10, 0x48, 0x83, 0xC4, 0x28, 0x48,
            0xFF, 0x60, 0x38, 0x33, 0xC0, 0x48, 0x83, 0xC4, 0x28, 0xC3,
        };
        // [0xE4D65E,0xE4D666): int3 int3 / mov eax,[rcx+20h] / ret / int3 int3.
        // With rcx = actor+0x10 this is the actor GUID at actor+0x30.
        constexpr std::uint8_t kActorGuidAccessor[] = {0xCC, 0xCC, 0x8B, 0x41, 0x20, 0xC3, 0xCC, 0xCC};
        // .rdata [0x5BF6808,0x5BF6810): interface vtable 0x5BF67D0 slot +0x38
        // = 0x140E4D660 (no ASLR: absolute VA in the certified image).
        constexpr std::uint8_t kActorIfaceGuidSlot[] = {0x60, 0xD6, 0xE4, 0x40, 0x01, 0x00, 0x00, 0x00};
        // .rdata [0x5BF6730,0x5BF6740): FSB actor vtable head (slots 0 and 1).
        constexpr std::uint8_t kActorVtableHead[] = {
            0x20, 0xED, 0xA4, 0x41, 0x01, 0x00, 0x00, 0x00, 0xA0, 0x2F, 0xE3, 0x40, 0x01, 0x00, 0x00, 0x00,
        };
        // [0x1B1F649,0x1B1F65D): call LocalClient / mov edx,[rsi+10h] /
        // mov rcx,[rax+0C8h] / call 0x1AACE90 -> r15 (the actor ApplyStat writes).
        constexpr std::uint8_t kApplyStatLookupCall[] = {
            0xE8, 0xF2, 0x85, 0xF7, 0xFF, 0x8B, 0x56, 0x10, 0x48, 0x8B, 0x88, 0xC8, 0x00, 0x00, 0x00, 0xE8,
            0x33, 0xD8, 0xF8, 0xFF,
        };
        // [0x1AACE90,0x1AACFA6): the WHOLE GUID lookup, all three .pdata
        // chunks (0x1AACE90, 0x1AACF13, 0x1AACF6C). Chunk 1 is the GUID ->
        // actor TMap probe (Num +0xA0 vs NumFree +0xCC, HashSize +0xE0, hash
        // inline +0xD0 / secondary +0xD8, elements +0x98 stride 0x18: key +0,
        // next +0x10, value [+8]). Chunk 2 calls 0xF8CCF0 on holder+0x48 with
        // the mapped actor pointer and returns it only when found; chunk 3
        // logs and returns null. v1.1.1 validated and mirrored chunk 1 only.
        constexpr std::uint8_t kGuidMapLookup[] = {
            0x40, 0x56, 0x48, 0x83, 0xEC, 0x30, 0x8B, 0x81, 0xA0, 0x00, 0x00, 0x00, 0x4C, 0x8B, 0xD9, 0x3B,
            0x81, 0xCC, 0x00, 0x00, 0x00, 0x74, 0x52, 0x4C, 0x63, 0x89, 0xE0, 0x00, 0x00, 0x00, 0x4C, 0x8D,
            0x91, 0xD0, 0x00, 0x00, 0x00, 0x4D, 0x8B, 0x42, 0x08, 0x49, 0xFF, 0xC9, 0x48, 0x63, 0xC2, 0x4C,
            0x23, 0xC8, 0x4D, 0x85, 0xC0, 0x4D, 0x0F, 0x45, 0xD0, 0x43, 0x8B, 0x04, 0x8A, 0x83, 0xF8, 0xFF,
            0x74, 0x27, 0x4C, 0x8B, 0x81, 0x98, 0x00, 0x00, 0x00, 0x0F, 0x1F, 0x80, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x48, 0x8D, 0x04, 0x49, 0x41, 0x39, 0x14, 0xC0, 0x49, 0x8D, 0x0C, 0xC0, 0x74,
            0x10, 0x8B, 0x41, 0x10, 0x83, 0xF8, 0xFF, 0x75, 0xE7, 0x33, 0xC0, 0x48, 0x83, 0xC4, 0x30, 0x5E,
            0xC3, 0x33, 0xF6, 0x48, 0x8D, 0x41, 0x08, 0x48, 0x85, 0xC9, 0x48, 0x0F, 0x44, 0xC6, 0x48, 0x85,
            0xC0, 0x74, 0xE6, 0x48, 0x89, 0x5C, 0x24, 0x48, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x48, 0x8B, 0x18,
            0x48, 0x89, 0x7C, 0x24, 0x50, 0x4C, 0x8B, 0xC3, 0x49, 0x8D, 0x7B, 0x48, 0x48, 0x8B, 0xCF, 0xE8,
            0xBC, 0xFD, 0x4D, 0xFF, 0x48, 0x63, 0x4C, 0x24, 0x40, 0x83, 0xF9, 0xFF, 0x74, 0x2E, 0x4C, 0x8D,
            0x04, 0x49, 0x48, 0x8B, 0x0F, 0x4A, 0x8D, 0x14, 0xC1, 0x48, 0x85, 0xD2, 0x48, 0x8D, 0x4A, 0x08,
            0x48, 0x0F, 0x44, 0xCE, 0x48, 0x85, 0xC9, 0x74, 0x13, 0x48, 0x8B, 0x7C, 0x24, 0x50, 0x48, 0x8B,
            0xC3, 0x48, 0x8B, 0x5C, 0x24, 0x48, 0x48, 0x83, 0xC4, 0x30, 0x5E, 0xC3, 0x48, 0x8D, 0x15, 0xBD,
            0xAF, 0x14, 0x04, 0x48, 0x89, 0x74, 0x24, 0x40, 0x48, 0x8D, 0x4C, 0x24, 0x20, 0xE8, 0x0E, 0x32,
            0xD5, 0x00, 0xE8, 0x29, 0xAD, 0xFE, 0xFF, 0x4C, 0x8B, 0xC6, 0x48, 0x8D, 0x54, 0x24, 0x20, 0xE8,
            0x1C, 0x40, 0x7D, 0x00, 0x48, 0x8B, 0x5C, 0x24, 0x48, 0x33, 0xC0, 0x48, 0x8B, 0x7C, 0x24, 0x50,
            0x48, 0x83, 0xC4, 0x30, 0x5E, 0xC3,
        };
        // [0xF8CCF0,0xF8CDFD): whole TSet<actor*> FindId used by chunk 2
        // (rcx = holder+0x48): Num +8 vs NumFree +0x34, PointerHash (key >> 4,
        // HashCombine with 0x9E3779B9), HashSize +0x48, hash inline +0x38 /
        // secondary +0x40, elements [+0] stride 0x18: key qword +0, next +0x10.
        constexpr std::uint8_t kLiveSetProbe[] = {
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x7C, 0x24, 0x10, 0x8B, 0x41, 0x08, 0x49, 0x8B, 0xD8,
            0x4C, 0x8B, 0xDA, 0x48, 0x8B, 0xF9, 0x3B, 0x41, 0x34, 0x0F, 0x84, 0xC8, 0x00, 0x00, 0x00, 0x48,
            0x8B, 0x57, 0x40, 0x4C, 0x8D, 0x47, 0x38, 0x4C, 0x8B, 0xD3, 0x41, 0xB9, 0xB9, 0x79, 0x37, 0x9E,
            0x49, 0xC1, 0xEA, 0x04, 0x45, 0x2B, 0xCA, 0x41, 0x8B, 0xC2, 0xC1, 0xE0, 0x08, 0x44, 0x33, 0xC8,
            0x41, 0x8B, 0xC1, 0xC1, 0xE8, 0x0D, 0x43, 0x8D, 0x0C, 0x11, 0x45, 0x2B, 0xD1, 0xF7, 0xD9, 0x33,
            0xC8, 0x44, 0x2B, 0xD1, 0x8B, 0xC1, 0xC1, 0xE8, 0x0C, 0x44, 0x33, 0xD0, 0x45, 0x2B, 0xCA, 0x41,
            0x8B, 0xC2, 0x44, 0x2B, 0xC9, 0xC1, 0xE0, 0x10, 0x44, 0x33, 0xC8, 0x41, 0x2B, 0xC9, 0x41, 0x8B,
            0xC1, 0xC1, 0xE8, 0x05, 0x41, 0x2B, 0xCA, 0x33, 0xC8, 0x45, 0x2B, 0xD1, 0x44, 0x2B, 0xD1, 0x8B,
            0xC1, 0xC1, 0xE8, 0x03, 0x44, 0x33, 0xD0, 0x45, 0x2B, 0xCA, 0x41, 0x8B, 0xC2, 0x44, 0x2B, 0xC9,
            0xC1, 0xE0, 0x0A, 0x44, 0x33, 0xC8, 0x41, 0x2B, 0xC9, 0x41, 0x8B, 0xC1, 0x48, 0xC1, 0xE8, 0x0F,
            0x41, 0x2B, 0xCA, 0x48, 0x63, 0xC9, 0x48, 0x33, 0xC8, 0x48, 0x63, 0x47, 0x48, 0x48, 0xFF, 0xC8,
            0x48, 0x23, 0xC8, 0x48, 0x85, 0xD2, 0x4C, 0x0F, 0x45, 0xC2, 0x41, 0x8B, 0x04, 0x88, 0x83, 0xF8,
            0xFF, 0x74, 0x24, 0x4C, 0x8B, 0x07, 0x66, 0x66, 0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x48, 0x8D, 0x14, 0x49, 0x49, 0x39, 0x1C, 0xD0, 0x74, 0x1F, 0x41, 0x8B, 0x44,
            0xD0, 0x10, 0x83, 0xF8, 0xFF, 0x75, 0xE9, 0x41, 0xC7, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0x49, 0x8B,
            0xC3, 0x48, 0x8B, 0x5C, 0x24, 0x08, 0x48, 0x8B, 0x7C, 0x24, 0x10, 0xC3, 0x48, 0x8B, 0x5C, 0x24,
            0x08, 0x48, 0x8B, 0x7C, 0x24, 0x10, 0x41, 0x89, 0x03, 0x49, 0x8B, 0xC3, 0xC3,
        };

        // ---- v1.3.1 ----------------------------------------------------------

        // [0x1BA87E6,0x1BA8823): the server-side stat apply 0x1BA8720 (40
        // damage/heal callers) calls ApplyStatDiff(E = [owner+0x60], stat, ctx,
        // diff, [rsp+20h] u8, [rsp+28h] u8, [rsp+30h] i32). Return 0x1BA8823.
        constexpr std::uint8_t kApplyStatDiffServerCall[] = {
            0x49, 0x8B, 0x4F, 0x60, 0x0F, 0x28, 0xD8, 0x4C, 0x8B, 0xC3, 0x8B, 0xD7, 0x0F, 0x28, 0xF8, 0xF3,
            0x0F, 0x2C, 0x81, 0x1C, 0x01, 0x00, 0x00, 0x89, 0x45, 0x40, 0x8B, 0x44, 0x24, 0x68, 0x89, 0x44,
            0x24, 0x30, 0x0F, 0xB6, 0x85, 0x00, 0x01, 0x00, 0x00, 0x88, 0x44, 0x24, 0x28, 0x0F, 0xB6, 0x85,
            0xF8, 0x00, 0x00, 0x00, 0x88, 0x44, 0x24, 0x20, 0xE8, 0xBD, 0xC4, 0xEB, 0xFF,
        };
        // [0x1BA8823,0x1BA8837): test al,al / je 0x1BA9683 (the function's
        // epilogue: no ApplyStat command, no pending death, no DeathTransition)
        // / mov rax,[r14] / movss xmm6,[rax+rdi*4+118h] (the new value).
        constexpr std::uint8_t kApplyStatDiffServerResult[] = {
            0x84, 0xC0, 0x0F, 0x84, 0x58, 0x0E, 0x00, 0x00, 0x49, 0x8B, 0x06, 0xF3, 0x0F, 0x10, 0xB4, 0xB8,
            0x18, 0x01, 0x00, 0x00,
        };
        // [0x1C71B1F,0x1C71B2C): call LocalClient 0x1A97C40 / mov rcx,rax /
        // call FSBGameWorld::Init 0x1C97CA0: the local-client cache holds the
        // FSBGameWorld the identity chain walks.
        constexpr std::uint8_t kGameWorldInitCall[] = {
            0xE8, 0x1C, 0x61, 0xE2, 0xFF, 0x48, 0x8B, 0xC8, 0xE8, 0x74, 0x61, 0x02, 0x00,
        };
        // [0x1C97E3E,0x1C97E4C) in Init (rsi = this since 0x1C97CC8): lea rdx,
        // [rip -> L"FSBGameWorld::Init, CurrentZoneInfo.ZoneAlias : %s,
        // EventorActorGUID : %d, ZoneGUID : %d"] / mov r9d,[rsi+80h] (the
        // first %d): EventorActorGUID lives at FSBGameWorld+0x80.
        constexpr std::uint8_t kEventorGuidInitLog[] = {
            0x48, 0x8D, 0x15, 0xDB, 0xCA, 0xF7, 0x03, 0x44, 0x8B, 0x8E, 0x80, 0x00, 0x00, 0x00,
        };

        // (v1.2.0: the TaskGraph signatures copied from SBMovementNative
        // v1.3.6 are gone; sbcore's gate validates the generated TaskGraph
        // manifest plus those exact legacy images before dispatch binds.)

        constexpr std::uint8_t kInt3 = 0xCC;

        void set_error(char (&buffer)[64], const char* text)
        {
            if (buffer[0] == '\0') std::snprintf(buffer, sizeof(buffer), "%s", text);
        }
    } // namespace

    const HookSite kSites[kSiteCount]{
        {"SetActorStat", "site_set_actor_stat_ok", 0x1A684F0, 16,
         kSetActorStatWindow, sizeof(kSetActorStatWindow), JumpBackRegister::Rax},
        {"ApplyStatExecute", "site_apply_stat_execute_ok", 0x1B1F620, 14,
         kApplyStatExecuteWindow, sizeof(kApplyStatExecuteWindow), JumpBackRegister::Rax},
        {"DeadExecute", "site_dead_execute_ok", 0x1B1FFF0, 15,
         kDeadExecuteWindow, sizeof(kDeadExecuteWindow), JumpBackRegister::R11},
        {"DeathTransition", "site_death_transition_ok", 0x1A6ED60, 18,
         kDeathTransitionWindow, sizeof(kDeathTransitionWindow), JumpBackRegister::R11},
        {"ActorStateChange", "site_actor_state_change_ok", 0x1A638C0, 20,
         kActorStateChangeWindow, sizeof(kActorStateChangeWindow), JumpBackRegister::R11},
        {"ApplyStatDiff", "site_apply_stat_diff_ok", kApplyStatDiffRva, 14,
         kApplyStatDiffWindow, sizeof(kApplyStatDiffWindow), JumpBackRegister::R11},
    };

    const Anchor kAnchors[kAnchorCount]{
        {"ApplyStatSetterCall", "anchor_apply_stat_setter_call_ok", 0x1B1F957,
         kApplyStatSetterCall, sizeof(kApplyStatSetterCall), RelKind::CallAtEnd, 0x1A684F0},
        {"ApplyStatDiffCall", "anchor_apply_stat_diff_call_ok", 0x1B1F7FC,
         kApplyStatDiffCall, sizeof(kApplyStatDiffCall), RelKind::None, 0},
        {"DeadExecuteFieldsCall", "anchor_dead_execute_fields_call_ok", 0x1B20167,
         kDeadExecuteFieldsCall, sizeof(kDeadExecuteFieldsCall), RelKind::CallAtEnd, 0x1A6ED60},
        {"DeadLocalCall", "anchor_dead_local_call_ok", 0x1BAE8A3,
         kDeadLocalCall, sizeof(kDeadLocalCall), RelKind::CallAtEnd, 0x1A6ED60},
        {"StateScopedCall", "anchor_state_scoped_call_ok", 0x1BADEBF,
         kStateScopedCall, sizeof(kStateScopedCall), RelKind::CallAtEnd, 0x1A638C0},
        {"GameThreadIdInit", "anchor_game_thread_id_init_ok", 0xE36F9B,
         kGameThreadIdInit, sizeof(kGameThreadIdInit), RelKind::RipDisp32At2, kGameThreadIdRva},
        {"LocalClientCacheLoad", "anchor_local_client_cache_load_ok", 0x1A97C44,
         kLocalClientCacheLoad, sizeof(kLocalClientCacheLoad), RelKind::RipDisp32At3, kLocalClientCacheRva},
        {"CurrentTargetGuid", "anchor_current_target_guid_ok", 0x1CC2590,
         kCurrentTargetGuid, sizeof(kCurrentTargetGuid), RelKind::None, 0},
        {"ActorGuidAccessor", "anchor_actor_guid_accessor_ok", 0xE4D65E,
         kActorGuidAccessor, sizeof(kActorGuidAccessor), RelKind::None, 0},
        {"ActorIfaceGuidSlot", "anchor_actor_iface_guid_slot_ok", kActorIfaceVtableRva + kActorIfaceGuidSlotOffset,
         kActorIfaceGuidSlot, sizeof(kActorIfaceGuidSlot), RelKind::None, 0, false},
        {"ActorVtableHead", "anchor_actor_vtable_head_ok", kActorVtableRva,
         kActorVtableHead, sizeof(kActorVtableHead), RelKind::None, 0, false},
        {"ApplyStatLookupCall", "anchor_apply_stat_lookup_call_ok", 0x1B1F649,
         kApplyStatLookupCall, sizeof(kApplyStatLookupCall), RelKind::CallAtEnd, kGuidMapLookupRva},
        {"GuidMapLookup", "anchor_guid_map_lookup_ok", kGuidMapLookupRva,
         kGuidMapLookup, sizeof(kGuidMapLookup), RelKind::None, 0},
        {"LiveSetProbe", "anchor_live_set_probe_ok", kLiveSetProbeRva,
         kLiveSetProbe, sizeof(kLiveSetProbe), RelKind::None, 0},
        {"ApplyStatDiffServerCall", "anchor_apply_stat_diff_server_call_ok", 0x1BA87E6,
         kApplyStatDiffServerCall, sizeof(kApplyStatDiffServerCall), RelKind::CallAtEnd, kApplyStatDiffRva},
        {"ApplyStatDiffServerResult", "anchor_apply_stat_diff_server_result_ok", kApplyDiffServerReturnRva,
         kApplyStatDiffServerResult, sizeof(kApplyStatDiffServerResult), RelKind::None, 0},
        {"GameWorldInitCall", "anchor_game_world_init_call_ok", 0x1C71B1F,
         kGameWorldInitCall, sizeof(kGameWorldInitCall), RelKind::CallAtEnd, kGameWorldInitRva},
        {"EventorGuidInitLog", "anchor_eventor_guid_init_log_ok", 0x1C97E3E,
         kEventorGuidInitLog, sizeof(kEventorGuidInitLog), RelKind::RipDisp32At3, kEventorInitLogFormatRva},
    };

    // The identity chain's compiled constants are exactly what the anchors prove.
    static_assert(sizeof(kCurrentTargetGuid) == 74 && sizeof(kGuidMapLookup) == 0x1AACFA6 - 0x1AACE90
                  && sizeof(kLiveSetProbe) == 0xF8CDFD - 0xF8CCF0);
    // Chunk 2 of the lookup calls exactly the live-set probe anchored above:
    // `mov r8,rbx / lea rdi,[r11+48h] / mov rcx,rdi / call 0xF8CCF0` at 0x1AACF25.
    constexpr std::int64_t rel32_at(const std::uint8_t* bytes, std::size_t at)
    {
        return static_cast<std::int32_t>(static_cast<std::uint32_t>(bytes[at]) | (static_cast<std::uint32_t>(bytes[at + 1]) << 8)
                                         | (static_cast<std::uint32_t>(bytes[at + 2]) << 16)
                                         | (static_cast<std::uint32_t>(bytes[at + 3]) << 24));
    }
    static_assert(kGuidMapLookup[0x98] == 0x49 && kGuidMapLookup[0x99] == 0x8D && kGuidMapLookup[0x9A] == 0x7B
                  && kGuidMapLookup[0x9B] == 0x48 && kGuidMapLookup[0x9F] == 0xE8
                  && 0x1AACF34 + rel32_at(kGuidMapLookup, 0xA0) == static_cast<std::int64_t>(kLiveSetProbeRva));
    static_assert(0x1A97C44 + 7 + 0x0559A925 == kLocalClientCacheRva);
    static_assert(0x140000000ULL + kActorGuidAccessorRva == 0x140E4D660ULL && kActorGuidAccessorRva == 0xE4D65E + 2);

    // The four return addresses must be exactly the end of their anchor.
    static_assert(0x1B201BF == 0x1B20167 + sizeof(kDeadExecuteFieldsCall));
    static_assert(0x1BAE8B1 == 0x1BAE8A3 + sizeof(kDeadLocalCall));
    static_assert(0x1BADED5 == 0x1BADEBF + sizeof(kStateScopedCall));
    static_assert(0x1B1F96A == 0x1B1F957 + sizeof(kApplyStatSetterCall));
    // v1.3.1: both ApplyStatDiff return addresses end a call to 0x1A64CE0.
    static_assert(kApplyDiffServerReturnRva == 0x1BA87E6 + sizeof(kApplyStatDiffServerCall));
    static_assert(kApplyStatDiffServerCall[sizeof(kApplyStatDiffServerCall) - 5] == 0xE8
                  && kApplyDiffServerReturnRva + rel32_at(kApplyStatDiffServerCall, sizeof(kApplyStatDiffServerCall) - 4)
                      == static_cast<std::int64_t>(kApplyStatDiffRva));
    // Inside the v1.1.0 ApplyStatDiffCall anchor (0x1B1F7FC): E8 at +0x2A.
    static_assert(kApplyStatDiffCall[0x2A] == 0xE8 && 0x1B1F7FC + 0x2A + 5 == kApplyDiffEchoReturnRva
                  && kApplyDiffEchoReturnRva + rel32_at(kApplyStatDiffCall, 0x2B) == static_cast<std::int64_t>(kApplyStatDiffRva));
    // test al,al / je rel32 -> 0x1BA9683 (the epilogue of the server apply).
    static_assert(kApplyStatDiffServerResult[0] == 0x84 && kApplyStatDiffServerResult[1] == 0xC0
                  && kApplyStatDiffServerResult[2] == 0x0F && kApplyStatDiffServerResult[3] == 0x84
                  && kApplyDiffServerReturnRva + 8 + rel32_at(kApplyStatDiffServerResult, 4) == 0x1BA9683);
    // LocalClient() (the getter whose cache the chain reads) feeds Init's this.
    static_assert(kGameWorldInitCall[0] == 0xE8 && 0x1C71B1F + 5 + rel32_at(kGameWorldInitCall, 1) == 0x1A97C40);
    static_assert(0x1C97E3E + 7 + rel32_at(kEventorGuidInitLog, 3) == static_cast<std::int64_t>(kEventorInitLogFormatRva));

    bool is_readable_region(const void* address, std::size_t size, bool require_executable)
    {
        if (!address || size == 0) return false;
        MEMORY_BASIC_INFORMATION info{};
        if (VirtualQuery(address, &info, sizeof(info)) != sizeof(info)
            || info.State != MEM_COMMIT
            || (info.Protect & (PAGE_GUARD | PAGE_NOACCESS)) != 0)
        {
            return false;
        }
        const auto start = reinterpret_cast<std::uintptr_t>(address);
        const auto end = reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize;
        if (start > end || size > end - start) return false;
        const DWORD executable =
            PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
        return !require_executable || (info.Protect & executable) != 0;
    }

    bool bytes_equal(const std::byte* address, const std::uint8_t* expected, std::size_t size, bool require_executable)
    {
        return is_readable_region(address, size, require_executable)
            && std::memcmp(address, expected, size) == 0;
    }

    namespace
    {
        std::uintptr_t rel32_destination(std::uintptr_t next_instruction_rva, const std::uint8_t* disp)
        {
            std::int32_t value{};
            std::memcpy(&value, disp, sizeof(value));
            return static_cast<std::uintptr_t>(static_cast<std::intptr_t>(next_instruction_rva) + value);
        }

        bool validate_site(const std::byte* image, const HookSite& site, bool require_executable)
        {
            if (site.patch_len < 12 || site.patch_len > 32 || site.window_len < site.patch_len) return false;
            const auto* target = image + site.rva;
            // Two bytes of int3 padding before the entry prove a function start.
            if (!is_readable_region(target - 2, 2 + site.window_len, require_executable)) return false;
            if (std::to_integer<std::uint8_t>(target[-1]) != kInt3
                || std::to_integer<std::uint8_t>(target[-2]) != kInt3)
            {
                return false;
            }
            return std::memcmp(target, site.window, site.window_len) == 0;
        }

        bool validate_anchor(const std::byte* image, const Anchor& anchor, bool require_executable)
        {
            const auto* at = image + anchor.rva;
            if (!bytes_equal(at, anchor.bytes, anchor.len, require_executable && anchor.code)) return false;
            switch (anchor.rel_kind)
            {
            case RelKind::None:
                return true;
            case RelKind::CallAtEnd:
                return anchor.len >= 5 && anchor.bytes[anchor.len - 5] == 0xE8
                    && rel32_destination(anchor.rva + anchor.len, anchor.bytes + anchor.len - 4)
                        == anchor.rel_target_rva;
            case RelKind::RipDisp32At2:
                return anchor.len >= 6
                    && rel32_destination(anchor.rva + 6, anchor.bytes + 2) == anchor.rel_target_rva;
            case RelKind::RipDisp32At3:
                return anchor.len >= 7
                    && rel32_destination(anchor.rva + 7, anchor.bytes + 3) == anchor.rel_target_rva;
            }
            return false;
        }
    } // namespace

    ValidationReport validate_image(const std::byte* image, bool require_executable)
    {
        ValidationReport report{};
        if (!image || !is_readable_region(image, sizeof(IMAGE_DOS_HEADER), false))
        {
            set_error(report.first_error, "image-unreadable");
            return report;
        }
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
        if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 0x1000)
        {
            set_error(report.first_error, "dos-header");
            return report;
        }
        const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
        if (!is_readable_region(nt, sizeof(*nt), false) || nt->Signature != IMAGE_NT_SIGNATURE)
        {
            set_error(report.first_error, "nt-header");
            return report;
        }
        report.timestamp = nt->FileHeader.TimeDateStamp;
        report.size_of_image = nt->OptionalHeader.SizeOfImage;
        report.machine = nt->FileHeader.Machine;
        report.headers_ok = report.machine == IMAGE_FILE_MACHINE_AMD64
            && report.timestamp == kExpectedTimestamp
            && report.size_of_image == kExpectedImageSize;
        if (!report.headers_ok)
        {
            // Wrong build: never read or trust any hard-coded RVA below.
            set_error(report.first_error, "build-mismatch");
            return report;
        }

        bool all = true;
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            report.site_ok[i] = validate_site(image, kSites[i], require_executable);
            if (!report.site_ok[i])
            {
                all = false;
                char text[64]{};
                std::snprintf(text, sizeof(text), "site-mismatch:%s", kSites[i].name);
                set_error(report.first_error, text);
            }
        }
        for (std::uint32_t i = 0; i < kAnchorCount; ++i)
        {
            report.anchor_ok[i] = validate_anchor(image, kAnchors[i], require_executable);
            if (!report.anchor_ok[i])
            {
                all = false;
                char text[64]{};
                std::snprintf(text, sizeof(text), "anchor-mismatch:%s", kAnchors[i].name);
                set_error(report.first_error, text);
            }
        }
        report.all_ok = all;
        return report;
    }

    namespace
    {
        constexpr std::size_t kTrampolineStride = 64;

        void write_entry_jump(std::uint8_t* p, std::size_t patch_len, const void* handler)
        {
            // mov rax, imm64 ; jmp rax ; int3/nop fill. RAX is not an argument
            // register in the x64 ABI, so clobbering it at entry is safe.
            p[0] = 0x48;
            p[1] = 0xB8;
            const auto value = reinterpret_cast<std::uint64_t>(handler);
            std::memcpy(p + 2, &value, sizeof(value));
            p[10] = 0xFF;
            p[11] = 0xE0;
            for (std::size_t i = 12; i < patch_len; ++i) p[i] = 0x90;
        }

        void build_trampoline(std::uint8_t* tramp, const HookSite& site, const std::byte* target)
        {
            std::memcpy(tramp, target, site.patch_len);
            const auto resume = reinterpret_cast<std::uint64_t>(target + site.patch_len);
            std::uint8_t* j = tramp + site.patch_len;
            if (site.jump_back == JumpBackRegister::R11)
            {
                j[0] = 0x49;
                j[1] = 0xBB;
                std::memcpy(j + 2, &resume, sizeof(resume));
                j[10] = 0x41;
                j[11] = 0xFF;
                j[12] = 0xE3;
                for (std::size_t i = 13; i < 16; ++i) j[i] = 0xCC;
            }
            else
            {
                j[0] = 0x48;
                j[1] = 0xB8;
                std::memcpy(j + 2, &resume, sizeof(resume));
                j[10] = 0xFF;
                j[11] = 0xE0;
                for (std::size_t i = 12; i < 16; ++i) j[i] = 0xCC;
            }
        }
    } // namespace

    bool patch_all(std::byte* image, void* const handlers[kSiteCount],
                   std::atomic<void*>* const original_slots[kSiteCount], PatchState& state)
    {
        if (state.installed) return true;
        state = PatchState{};
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            if (!handlers[i] || !original_slots[i])
            {
                set_error(state.error, "null-handler");
                return false;
            }
        }

        // 1. Re-validate every site immediately before touching anything.
        const auto report = validate_image(image, true);
        if (!report.all_ok)
        {
            set_error(state.error, report.first_error[0] ? report.first_error : "validation-failed");
            return false;
        }

        // 2. Allocate and build every trampoline (our own memory only).
        auto* block = static_cast<std::uint8_t*>(
            VirtualAlloc(nullptr, kTrampolineStride * kSiteCount, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
        if (!block)
        {
            set_error(state.error, "trampoline-alloc");
            return false;
        }
        std::memset(block, 0xCC, kTrampolineStride * kSiteCount);
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            const auto* target = image + kSites[i].rva;
            std::memcpy(state.saved[i], target, kSites[i].patch_len);
            state.saved_len[i] = kSites[i].patch_len;
            build_trampoline(block + i * kTrampolineStride, kSites[i], target);
        }
        DWORD block_old{};
        if (!VirtualProtect(block, kTrampolineStride * kSiteCount, PAGE_EXECUTE_READ, &block_old))
        {
            VirtualFree(block, 0, MEM_RELEASE);
            set_error(state.error, "trampoline-protect");
            return false;
        }
        FlushInstructionCache(GetCurrentProcess(), block, kTrampolineStride * kSiteCount);

        // 3. Make every target writable before the first code byte changes.
        DWORD old_protect[kSiteCount]{};
        std::uint32_t unlocked = 0;
        for (; unlocked < kSiteCount; ++unlocked)
        {
            if (!VirtualProtect(image + kSites[unlocked].rva, kSites[unlocked].patch_len,
                                PAGE_EXECUTE_READWRITE, &old_protect[unlocked]))
            {
                break;
            }
        }
        if (unlocked != kSiteCount)
        {
            for (std::uint32_t i = 0; i < unlocked; ++i)
            {
                DWORD ignored{};
                VirtualProtect(image + kSites[i].rva, kSites[i].patch_len, old_protect[i], &ignored);
            }
            VirtualFree(block, 0, MEM_RELEASE);
            char text[64]{};
            std::snprintf(text, sizeof(text), "protect-failed:%s", kSites[unlocked].name);
            set_error(state.error, text);
            return false;
        }

        // 4. Final byte re-check under the unlocked protection, then write.
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            if (std::memcmp(image + kSites[i].rva, kSites[i].window, kSites[i].patch_len) != 0)
            {
                for (std::uint32_t k = 0; k < kSiteCount; ++k)
                {
                    DWORD ignored{};
                    VirtualProtect(image + kSites[k].rva, kSites[k].patch_len, old_protect[k], &ignored);
                }
                VirtualFree(block, 0, MEM_RELEASE);
                set_error(state.error, "late-mismatch");
                return false;
            }
        }
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            state.originals[i] = block + i * kTrampolineStride;
            original_slots[i]->store(state.originals[i], std::memory_order_seq_cst);
        }
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            auto* target = reinterpret_cast<std::uint8_t*>(image + kSites[i].rva);
            write_entry_jump(target, kSites[i].patch_len, handlers[i]);
        }
        for (std::uint32_t i = 0; i < kSiteCount; ++i)
        {
            DWORD ignored{};
            VirtualProtect(image + kSites[i].rva, kSites[i].patch_len, old_protect[i], &ignored);
            FlushInstructionCache(GetCurrentProcess(), image + kSites[i].rva, kSites[i].patch_len);
        }
        state.trampoline_block = block;
        state.installed = true;
        return true;
    }
} // namespace sbgod::sites
