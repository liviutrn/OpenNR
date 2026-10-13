#include "joey_plugin/CopyFlow.hpp"
#include <cassert>
using namespace duoview_joey;
int main() {
 assert(choose_copy({true,false,false,false,false,false,true})==CopyAction::Native);
 assert(choose_copy({false,true,true,true,true,true,true})==CopyAction::Compose);
 assert(choose_copy({false,true,false,true,true,true,true})==CopyAction::Hold);
 assert(choose_copy({false,true,true,false,true,true,true})==CopyAction::Hold);
 assert(choose_copy({false,false,false,true,false,true,true})==CopyAction::Hold);
 assert(choose_copy({false,true,true,true,true,true,false})==CopyAction::Reject);
 assert(choose_copy({false,true,false,true,true,false,true})==CopyAction::Reject);
 CopyProof p{true,true,true,false,true,10,11};assert(p.queued());
 auto bad=p;bad.recorded=false;assert(!bad.queued()); // empty original copy may return true
 bad=p;bad.original_returned=false;assert(!bad.queued());
 bad=p;bad.destination_verified=false;assert(!bad.queued());
 bad=p;bad.poisoned=true;assert(!bad.queued());
 bad=p;bad.fence_after=10;assert(!bad.queued());
 bad=p;bad.waiting=false;assert(!bad.queued());
}
