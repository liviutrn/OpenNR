#include "DuoViewSubmission.hpp"
#include <cassert>
#include <thread>
#include <atomic>
using uevr::duoview::SubmissionMailbox;
struct Packet { int identity{}; };
int main() {
    SubmissionMailbox<Packet,3> mailbox;
    assert(!mailbox.publish(0, 1, 1, {1}));
    assert(!mailbox.publish(100, 0, 1, {1}));
    assert(!mailbox.publish(100, 1, 0, {1}));
    std::atomic<bool> published{false};
    std::thread producer([&] {
        assert(mailbox.publish(100,1,10,{10}));
        published.store(true,std::memory_order_release);
    });
    std::thread consumer([&] {
        while(!published.load(std::memory_order_acquire)) std::this_thread::yield();
        assert(!mailbox.take(101,1));
        auto value=mailbox.take(100,1);
        assert(value && value->identity==10);
        assert(!mailbox.take(100,1));
    });
    producer.join(); consumer.join();
    assert(mailbox.publish(200,1,20,{20}));
    assert(!mailbox.publish(200,1,21,{21}));
    assert(!mailbox.take(200,2)); // generation mismatch drops stale frame
    assert(!mailbox.take(200,1));
    assert(mailbox.publish(300,1,30,{30}));
    assert(mailbox.publish(400,1,40,{40}));
    assert(mailbox.publish(500,1,50,{50}));
    assert(mailbox.publish(600,1,60,{60})); // bounded eviction
    assert(mailbox.pending()==3);
    assert(!mailbox.take(300,1));
    assert(mailbox.take(400,1)->identity==40);
    mailbox.retire();
    assert(!mailbox.take(500,1));
    assert(mailbox.pending()==0);
}
