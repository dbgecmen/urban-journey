import asyncio
from traceback import print_exception
import sys

from urban_journey.pubsub.trigger import TriggerBase
from urban_journey.pubsub.descriptor.instance import DescriptorInstance
from urban_journey.pubsub.descriptor.static import DescriptorStatic
from urban_journey import event_loop


# TODO: Add a clock that can be created dynamically.


class ClockStatic(DescriptorStatic, TriggerBase):
    """
    Class used to statically declare a clock using a descriptor.
    """
    def __init__(self):
        DescriptorStatic.__init__(self, ClockInstance)
        TriggerBase.__init__(self)

    def add_obj(self, obj):
        t = self.instances_base_class(obj,
                                      self.attribute_name,
                                      self)
        self.instances[id(obj)] = t
        for activity in self._activities:
            t.add_activity(activity)

    def add_activity(self, activity):
        super().add_activity(activity)
        for _, t in self.instances.items():
            t.add_activity(activity)

    def remove_activity(self, activity):
        super().remove_activity(activity)
        for _, t in self.instances.items():
            t.remove_activity(activity)

    def trigger(self, s):
        for _, t in self.instances.items():
            # TODO: Fix this.
            # This will cause an error. But I'll deal with that later.
            t.trigger(None)


class ClockInstance(DescriptorInstance, TriggerBase):
    """
    Class used to create clock instances for statically/descriptor defined clocks.
    """

    def __init__(self, parent_object, attribute_name, static_descriptor):
        TriggerBase.__init__(self)
        DescriptorInstance.__init__(self, parent_object, attribute_name, static_descriptor)

        self.loop = event_loop.get()  #: main event loop.
        self.period = 1  #: Clock period.
        self.running = False  #: True if the clock is running.

    @property
    def frequency(self):
        """
        Clock frequency.
        :return:
        """
        return 1 / self.period

    @frequency.setter
    def frequency(self, value):
        self.period = 1 / value

    def start(self):
        """
        Starts the clock

        :return: Returns an Asyncio.Future object that completes after the first tick.
        """
        self.running = True
        return asyncio.run_coroutine_threadsafe(self.timer_callback(), loop=self.loop)

    def stop(self):
        """
        Stop the clock.
        """
        self.running = False

    async def timer_callback(self):
        """
        Co-routine that schedules the clock ticks.

        """
        while self.running:
            await asyncio.sleep(self.period)
            await self.trigger()

    async def trigger(self):
        """
        Triggers all connected activities.
        """
        for activity in self._activities:
            try:
                await activity.trigger([self], {}, self.parent_object)
            except:
                print_exception(*sys.exc_info())
                assert False
