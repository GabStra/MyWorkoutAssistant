package com.gabstra.myworkoutassistant

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun Modifier.verticalColumnScrollbarContainer(
    scrollState: ScrollState,
    enabled: Boolean = true,
): Modifier = this
    .verticalColumnScrollbar(scrollState)
    .verticalScroll(scrollState, enabled = enabled)
    .padding(horizontal = Spacing.md)
