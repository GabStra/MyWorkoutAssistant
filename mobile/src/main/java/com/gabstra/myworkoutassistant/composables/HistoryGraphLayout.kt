package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import com.gabstra.myworkoutassistant.Spacing

@Composable
fun ColumnScope.HistoryGraphTabColumn(
    scrollState: ScrollState,
    isScrollEnabled: Boolean,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .weight(1f)
            .fillMaxSize()
            .verticalScroll(
                state = scrollState,
                enabled = isScrollEnabled,
            )
            .padding(horizontal = Spacing.md)
            .padding(bottom = Spacing.md),
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
        content = content,
    )
}

@Composable
fun ColumnScope.HistorySetsTabColumn(
    state: LazyListState,
    content: LazyListScope.() -> Unit,
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .weight(1f)
            .fillMaxSize()
            .padding(horizontal = Spacing.md)
            .padding(bottom = Spacing.md),
        state = state,
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
        content = content,
    )
}

@Composable
fun HistoryGraphEmptyState(
    text: String,
    modifier: Modifier = Modifier,
) {
    PrimarySurface(
        modifier = modifier.fillMaxWidth()
    ) {
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacing.lg),
            text = text,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
