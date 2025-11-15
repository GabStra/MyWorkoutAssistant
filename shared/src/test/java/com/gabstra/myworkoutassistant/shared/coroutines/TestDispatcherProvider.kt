package com.gabstra.myworkoutassistant.shared.coroutines

import kotlinx.coroutines.CoroutineDispatcher

class TestDispatcherProvider(
    override val main: CoroutineDispatcher,
    override val io: CoroutineDispatcher = main,
    override val default: CoroutineDispatcher = main
) : DispatcherProvider

