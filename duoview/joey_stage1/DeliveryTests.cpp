#ifdef _WIN32
#include <windows.h>
#endif
#include "DuoViewDelivery.hpp"
#include <cassert>
#include <atomic>
#include <thread>
#include <iostream>
#include <unordered_map>

struct Packet { uint64_t serial; uint32_t immutable_pose; };
using Delivery = uevr::duoview::Delivery<Packet>;
using Role = uevr::duoview::SourceRole;
Delivery::Source source(std::shared_ptr<const Packet> p, uint32_t family, Role role, uint64_t gen=1) {
    return {p, gen, role==Role::primary ? 100u:200u, 300, family, role};
}
void bind(Delivery& delivery, const std::shared_ptr<const Packet>& p, uint32_t family, uint64_t gen=1) {
    assert(delivery.family(source(p,family,Role::primary,gen),1));
    assert(delivery.family(source(p,family+1,Role::secondary,gen),1));
}
void execute(Delivery& delivery, uint32_t family, Role role, uint64_t gen=1) {
    const auto s=delivery.render(gen,family,role==Role::primary ? 100u:200u,300,2);
    assert(s);
    delivery.executed(s,family+1000,3);
}
int main() {
    auto delivery_storage=std::make_unique<Delivery>();
    auto& delivery=*delivery_storage;
    auto a=std::make_shared<const Packet>(Packet{1,700});
    auto b=std::make_shared<const Packet>(Packet{2,702});
    auto c=std::make_shared<const Packet>(Packet{3,704});
    bind(delivery,a,20);bind(delivery,b,22);bind(delivery,c,24);
    assert(!delivery.select(1,3)); // GT is ahead; no source executed yet.
    execute(delivery,20,Role::primary);
    assert(!delivery.select(1,3));
    execute(delivery,21,Role::secondary);
    assert(delivery.select(1,3)==a);
    assert(delivery.select(1,3)->immutable_pose==700);
    assert(delivery.select(1,3)==a); // Duplicate Present is still the same transaction.
    assert(!delivery.select(1,4)); // Unordered parallel thread cannot claim source completion.
    execute(delivery,22,Role::primary);
    assert(!delivery.select(1,3)); // Persistent resource pointer does not excuse mixed contents.
    execute(delivery,23,Role::secondary);
    assert(delivery.select(1,3)==b);
    auto unknown=delivery.render(1,500,100,300,2);
    assert(unknown && !unknown.packet);
    delivery.executed(unknown,9000,3);
    assert(!delivery.select(1,3)); // An unbound source write invalidates the old pair.
    execute(delivery,24,Role::primary);execute(delivery,25,Role::secondary);
    assert(delivery.select(1,3)==c);
    assert(!delivery.render(1,800,999,300,2)); // Auxiliary target is inert.
    assert(delivery.select(1,3)==c);
    assert(!delivery.select(2,3)); // Mode/resize generation cannot inherit old images.
    delivery.executed(source(c,25,Role::secondary),9001,3);
    assert(!delivery.select(2,3)); // A delayed old callback cannot regress the generation.
    bind(delivery,a,0xffffffffu,2);
    execute(delivery,0xffffffffu,Role::primary,2);execute(delivery,0,Role::secondary,2);
    assert(delivery.select(2,3)==a); // Exact unsigned family identity survives wrap.
    Delivery::Source immutable=source(a,100,Role::primary);
    assert(immutable.same_owner(immutable));
    assert(!immutable.same_owner(source(b,102,Role::primary)));
    assert(!immutable.same_owner(source(a,101,Role::secondary)));

    Delivery::Command slate;
    const auto primary=source(a,20,Role::primary);
    const auto secondary=source(a,21,Role::secondary);
    assert(slate.attach(primary)==Delivery::Attachment::added);
    assert(slate.attach(primary)==Delivery::Attachment::duplicate);
    assert(slate.attach(secondary)==Delivery::Attachment::added);
    assert(slate.owner().frame==20 && slate.sources[1].frame==21);
    assert(slate.attach(source(b,22,Role::primary))==Delivery::Attachment::conflict);
    assert(slate.attach(source(b,23,Role::secondary))==Delivery::Attachment::conflict);
    assert(slate.sources[0].packet==a && slate.sources[1].packet==a);
    Delivery::Command reverse_slate;
    assert(reverse_slate.attach(secondary)==Delivery::Attachment::added);
    assert(reverse_slate.attach(primary)==Delivery::Attachment::added);
    assert(reverse_slate.sources[1].frame==21 && reverse_slate.owner().frame==21);

    std::unordered_map<uintptr_t,uintptr_t> links{{1,2},{2,3},{3,0}};
    const auto read=[&](uintptr_t p)->std::optional<uintptr_t>{
        const auto found=links.find(p);return found==links.end()?std::nullopt:std::optional{found->second};};
    assert(uevr::duoview::command_tail(1,read)==3);
    links[3]=4;links[4]=0;
    assert(uevr::duoview::command_tail(1,read)==4); // Same root, later work gets its own tail.
    links[4]=2;
    assert(!uevr::duoview::command_tail(1,read)); // Cycle is bounded.
    assert(!uevr::duoview::command_tail(100,read));
    assert(!uevr::duoview::command_tail(0,read));

    auto concurrent_storage=std::make_unique<Delivery>();
    auto& concurrent=*concurrent_storage;
    std::atomic<uint32_t> registered{},retired{};
    constexpr uint32_t count=100000;
    std::thread producer([&]{
        for(uint32_t i=1;i<=count;++i) {
            while(i>retired.load(std::memory_order_acquire)+8) std::this_thread::yield();
            bind(concurrent,std::make_shared<const Packet>(Packet{i,i*2+100}),i*2);
            registered.store(i,std::memory_order_release);
        }
    });
    for(uint32_t i=1;i<=count;++i) {
        while(registered.load(std::memory_order_acquire)<i) std::this_thread::yield();
        const auto p=concurrent.render(1,i*2,100,300,2);
        const auto s=concurrent.render(1,i*2+1,200,300,2);
        Delivery::Command command;
        assert(command.attach(p)==Delivery::Attachment::added);
        if (i%2) {
            assert(command.attach(s)==Delivery::Attachment::added);
            for (const auto& role : command.sources) concurrent.executed(role,i+1000,3);
        } else {
            concurrent.executed(p,i+1000,3);
            assert(!concurrent.select(1,3));
            concurrent.executed(s,i+1001,3);
        }
        const auto packet=concurrent.select(1,3);
        assert(packet && packet->serial==i && packet->immutable_pose==i*2+100);
        concurrent.result(uevr::duoview::DeliveryEvent::copy,i,true,3);
        concurrent.result(uevr::duoview::DeliveryEvent::submit,i,true,3);
        retired.store(i,std::memory_order_release);
    }
    producer.join();
    const auto counts=concurrent.counts();
    assert(counts.produced==count && counts.ready==count && counts.matched==count);
    assert(counts.enqueued==count && counts.submitted==count && counts.overwritten==0 && counts.failed==0);
    concurrent.result(uevr::duoview::DeliveryEvent::submit,count,true,3);
    assert(concurrent.counts().submitted==count && concurrent.counts().duplicate_presents==1);
    concurrent.result(uevr::duoview::DeliveryEvent::submit,count,false,3);
    assert(concurrent.counts().submitted==count && concurrent.counts().failed==1);
    concurrent.reset_counts();
    assert(concurrent.counts().submitted==0 && concurrent.counts().produced==0);
    assert(concurrent.select(1,3)->serial==count);

    auto blocked_storage=std::make_unique<Delivery>();
    auto& blocked=*blocked_storage;
    bind(blocked,a,10); execute(blocked,10,Role::primary);execute(blocked,11,Role::secondary);
    blocked.block(source(b,12,Role::primary),123,2);
    assert(!blocked.select(1,3));
    assert(!blocked.family(source(b,12,Role::primary),1));
    execute(blocked,12,Role::primary);execute(blocked,13,Role::secondary);
    assert(!blocked.select(1,3));
    bind(blocked,c,14);execute(blocked,14,Role::primary);execute(blocked,15,Role::secondary);
    assert(blocked.select(1,3)==c);

    auto bounded_storage=std::make_unique<uevr::duoview::Delivery<Packet,2>>();
    auto& bounded=*bounded_storage;
    assert(bounded.family({a,1,100,300,1,Role::primary},1));
    assert(bounded.family({a,1,200,300,2,Role::secondary},1));
    assert(!bounded.family({b,1,100,300,3,Role::primary},1));
    assert(bounded.render(1,1,100,300,2).packet==a);

    auto lifetime_storage=std::make_unique<Delivery>();
    auto& lifetime=*lifetime_storage;
    auto owned=std::make_shared<const Packet>(Packet{1,500});
    std::weak_ptr<const Packet> weak=owned;
    bind(lifetime,owned,30); owned.reset();
    assert(!weak.expired());
    execute(lifetime,30,Role::primary);execute(lifetime,31,Role::secondary);
    assert(lifetime.select(1,3)->immutable_pose==500);
    assert(!lifetime.select(2,3));
    assert(weak.expired());
    auto idle_storage=std::make_unique<Delivery>();
    auto& idle=*idle_storage;
    auto retiring=std::make_shared<const Packet>(Packet{1,900});
    std::weak_ptr<const Packet> retained=retiring;
    bind(idle,retiring,50);
    Delivery::Command pending;
    auto p=idle.render(1,50,100,300,2);
    auto q=idle.render(1,51,200,300,2);
    assert(pending.attach(p)==Delivery::Attachment::added);
    assert(pending.attach(q)==Delivery::Attachment::added);
    idle.executed(p,4000,3);idle.executed(q,4000,3);
    p={};q={};retiring.reset();
    idle.retire();
    assert(!retained.expired());
    for(const auto& s:pending.sources) idle.executed(s,4000,3);
    assert(!idle.select(1,3));
    pending={};
    assert(retained.expired());
    bind(idle,b,52);execute(idle,52,Role::primary);execute(idle,53,Role::secondary);
    assert(idle.select(1,3)==b);
    idle.retire(2);
    assert(!idle.select(2,3));

    std::cout << "100000 source/pose transactions, producer 0-8 ahead: no wrong selection or missed completed pair\n";
}
