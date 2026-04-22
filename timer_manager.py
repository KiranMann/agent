"""Timer Management Module.

This module provides a comprehensive timer management system for asynchronous operations.
It enables the creation and management of multiple timers that run independently in a
separate thread with their own event loop, preventing blocking of the main application thread.

The module consists of three main components:

1. TimerClient: An abstract base class that defines the interface for objects that want
   to receive timer notifications. Clients must implement the on_timer() and
   on_timer_lapsed() methods to handle timer events.

2. TimerManager: The central manager that coordinates all timer operations. It runs
   in a separate daemon thread with its own asyncio event loop, allowing multiple
   timers to execute concurrently without interfering with the main application.

3. BotTimer: Individual timer instances that handle the actual timing logic, including
   initial delays, repeat intervals, and repeat counts. Each timer notifies its
   associated client when events occur.

Key Features:
- Thread-safe timer operations
- Support for initial delays before first timer event
- Configurable repeat intervals and counts
- Infinite repeat capability (-1 repeats)
- Proper cleanup and cancellation support
- Asynchronous callback execution

Usage Example:
    class MyTimerClient(TimerClient):
        async def on_timer(self, tid: int):
            print(f"Timer {tid} fired!")

        async def on_timer_lapsed(self, tid: int):
            print(f"Timer {tid} completed!")

    client = MyTimerClient()
    timer_id = timer_manager.add_timer(client, init_start=5, interval=10, repeats=3)

Global Instance:
    timer_manager: A singleton TimerManager instance ready for immediate use.
"""

from __future__ import annotations

import asyncio
from threading import Thread
from typing import TYPE_CHECKING, Any

from common.logging.core import logger

if TYPE_CHECKING:
    from concurrent.futures import Future


class TimerClient:
    """Base class for timer clients that can receive timer events.

    This class provides the interface that clients must implement to receive
    timer notifications from the TimerManager. Subclasses should override
    the on_timer and on_timer_lapsed methods to handle timer events.
    """

    def __init__(self) -> None:
        """Initialize the timer client with an empty timer context."""
        self.timercontext: dict[str, Any] = {}

    async def on_timer(self, tid: int) -> None:  # pylint: disable=unused-argument  # noqa: ARG002
        """Called when a timer fires.

        This method is called periodically based on the timer's interval.
        Subclasses should override this method to implement their timer logic.

        Args:
            tid (int): The unique timer ID that fired.
        """
        return

    async def on_timer_lapsed(self, tid: int) -> None:  # pylint: disable=unused-argument  # noqa: ARG002
        """Called when a timer has completed all its repetitions.

        This method is called once when a timer finishes executing, either
        because it reached its repeat limit or was cancelled.

        Args:
            tid (int): The unique timer ID that has lapsed.
        """
        return


class TimerManager:
    """Manages asynchronous timers in a separate thread.

    The TimerManager provides a way to create and manage multiple timers
    that run asynchronously. It uses a separate thread with its own event
    loop to handle timer execution without blocking the main thread.

    Attributes:
        _loop: The asyncio event loop running in the timer thread.
        _timers: Dictionary mapping timer IDs to BotTimer instances.
        _next_timer_id: Counter for generating unique timer IDs.
        _run_thread: The thread running the event loop.
    """

    def __init__(self) -> None:
        """Initialize the TimerManager and start the timer thread.

        Creates a new event loop, initializes internal data structures,
        and starts a daemon thread to run the event loop.
        """
        self._loop = asyncio.new_event_loop()
        self._timers: dict[int, BotTimer] = {}
        self._next_timer_id = 1
        self._run_thread: Thread | None = Thread(target=self._start_run_thread, daemon=True)
        self._run_thread.start()
        logger.info("TimerManager initialised")

    def fini(self) -> None:
        """Shutdown the TimerManager and clean up resources.

        Cancels all active timers, stops the event loop, and cleans up
        the timer thread. This method should be called before the
        application exits.
        """
        logger.info("shutting down TimerManager")
        if not self._run_thread:
            return
        for timer in self._timers.values():
            timer.cancel()

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._timers = {}

    def is_running(self) -> bool:
        """Check if the TimerManager is currently running.

        Returns:
            bool: True if the timer thread is active, False otherwise.
        """
        return self._run_thread is not None

    def _start_run_thread(self) -> None:
        """Entry point for the timer thread.

        Sets up the event loop for the current thread and runs it forever.
        If an exception occurs, it logs the error and marks the thread
        as no longer running.
        """
        try:
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        except Exception as e:
            logger.error(f"Unable to run event loop, error {e}")

        self._run_thread = None

    def add_timer(
        self,
        client: TimerClient,
        init_start: int = 0,
        interval: int = 1,
        repeats: int = -1,
    ) -> int:
        """Create and add a new timer.

        Args:
            client (TimerClient): The client that will receive timer events.
            init_start (int, optional): Initial delay before first timer event in seconds. Defaults to 0.
            interval (int, optional): Interval between timer events in seconds. Defaults to 1.
            repeats (int, optional): Number of times to repeat the timer. -1 for infinite. Defaults to -1.

        Returns:
            int: The unique timer ID that can be used to reference this timer.
        """
        timer_id: int = self._next_timer_id
        self._next_timer_id = self._next_timer_id + 1
        self._timers[timer_id] = BotTimer(
            bid=timer_id,
            loop=self._loop,
            client=client,
            init_start=init_start,
            interval=interval,
            repeats=repeats,
        )
        return timer_id

    def add_task(self, coro: Any) -> Future[Any]:
        """Schedule a coroutine to run in the timer thread's event loop.

        Args:
            coro: The coroutine to execute in the timer thread.

        Returns:
            concurrent.futures.Future: A Future representing the execution of the coroutine.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def del_timer(self, timer_id: int) -> None:
        """Cancel and remove a timer.

        Args:
            timer_id (int): The ID of the timer to remove.
        """
        if timer_id not in self._timers:
            logger.error(f"Timer {timer_id} does not exist")
            return

        timer = self._timers[timer_id]
        timer.cancel()
        del self._timers[timer_id]


class BotTimer:
    """Individual timer that executes client callbacks at specified intervals.

    BotTimer handles the execution of a single timer, including initial delays,
    repeat intervals, and repeat counts. It runs asynchronously and notifies
    the client when timer events occur.

    Attributes:
        id (int): Unique identifier for this timer.
        _loop: The event loop this timer runs in.
        _client (TimerClient): The client to notify of timer events.
        _init_start (int): Initial delay before first timer event.
        _repeats (int): Number of repetitions remaining (-1 for infinite).
        _interval (int): Interval between timer events in seconds.
        _is_running (bool): Whether the timer is currently active.
        _task: The asyncio task executing the timer logic.
    """

    def __init__(
        self,
        bid: int,
        loop: asyncio.AbstractEventLoop,
        client: TimerClient,
        init_start: int = 0,
        interval: int = 1,
        repeats: int = -1,
    ) -> None:
        """Initialize a new timer.

        Args:
            bid (int): Unique timer ID (note: parameter name should be 'id' but uses 'bid').
            loop: The asyncio event loop to run the timer in.
            client (TimerClient): The client that will receive timer notifications.
            init_start (int, optional): Initial delay before first event in seconds. Defaults to 0.
            interval (int, optional): Interval between events in seconds. Defaults to 1.
            repeats (int, optional): Number of repetitions (-1 for infinite). Defaults to -1.
        """
        self.id: int = bid
        self._loop: asyncio.AbstractEventLoop = loop
        self._client: TimerClient = client
        self._init_start: int = init_start
        self._repeats: int = repeats
        self._interval: int = interval
        self._is_running: bool = True
        self._task: Future[None] = asyncio.run_coroutine_threadsafe(self._job(), self._loop)
        logger.debug("Add a new timer")

    async def _job(self) -> None:
        """Main timer execution coroutine.

        Handles the timer lifecycle including initial delay, periodic execution,
        and repeat counting. Notifies the client of timer events and completion.
        """
        if self._init_start > 0:
            await asyncio.sleep(self._init_start)
        await self._client.on_timer(self.id)
        if self._repeats < 0:
            while self._is_running:
                await asyncio.sleep(self._interval)
                await self._client.on_timer(self.id)
        else:
            while self._repeats > 0:
                await asyncio.sleep(self._interval)
                await self._client.on_timer(self.id)
                self._repeats -= 1

        await self._client.on_timer_lapsed(self.id)
        self._is_running = False

    def is_active(self) -> bool:
        """Check if the timer is currently active.

        Returns:
            bool: True if the timer is running, False if stopped or cancelled.
        """
        return self._is_running

    def cancel(self) -> None:
        """Cancel the timer and stop its execution.

        Cancels the underlying asyncio task and marks the timer as not running.
        The timer will not fire any more events after this method is called.
        """
        self._task.cancel()
        self._is_running = False


timer_manager = TimerManager()
