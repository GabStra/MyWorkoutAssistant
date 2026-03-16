package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.ScrollInfoProvider
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import java.util.Locale.getDefault

/** A section with a title and a list of lines (e.g. "Equipment" / ["Barbell"] or "Accessories" / ["Bench", "Rings"]). */
data class TitledLinesSection(val title: String, val lines: List<String>)

@Composable
private fun TitledLinesSectionItem(
    section: TitledLinesSection,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier,
    ) {
        Text(
            text = section.title.uppercase(getDefault()),
            modifier = Modifier.fillMaxWidth(),
            style = workoutPagerTitleTextStyle(),
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center
        )
        section.lines.forEach { line ->
            Text(
                text = line,
                modifier = Modifier.padding(top = 5.dp).fillMaxWidth(),
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center
            )
        }
    }
}

/**
 * Full-screen scrollable page that shows a list of sections, each with a bold title and lines.
 * No buttons; navigation/dismiss is handled by the parent (e.g. back gesture).
 * Use for content like "Equipment: Barbell" and "Accessories: Bench, Rings".
 */
@Composable
fun PageTitledLines(
    sections: List<TitledLinesSection>,
    modifier: Modifier = Modifier
) {
    val state = rememberLazyListState()
    val scrollInfoProvider = remember(state) {
        object : ScrollInfoProvider {
            override val isScrollAwayValid: Boolean
                get() = state.layoutInfo.totalItemsCount > 0

            override val isScrollable: Boolean
                get() = state.canScrollBackward || state.canScrollForward

            override val isScrollInProgress: Boolean
                get() = state.isScrollInProgress

            override val anchorItemOffset: Float
                get() = state.layoutInfo.visibleItemsInfo.firstOrNull()?.let {
                    if (it.index != 0) {
                        Float.NaN
                    } else {
                        -it.offset.toFloat()
                    }
                } ?: Float.NaN

            override val lastItemOffset: Float
                get() {
                    val layoutInfo = state.layoutInfo
                    val viewportHeight = layoutInfo.viewportSize.height
                    return layoutInfo.visibleItemsInfo.lastOrNull()?.let { item ->
                        if (item.index != layoutInfo.totalItemsCount - 1) {
                            0f
                        } else {
                            val bottomEdge = item.offset + item.size - layoutInfo.viewportStartOffset
                            (viewportHeight - bottomEdge).toFloat().coerceAtLeast(0f)
                        }
                    } ?: 0f
                }
        }
    }

    ScreenScaffold(
        modifier = modifier,
        scrollInfoProvider = scrollInfoProvider,
        scrollIndicator = {
            ScrollIndicator(
                state = state,
                colors = ScrollIndicatorDefaults.colors(
                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                    trackColor = MediumDarkGray
                )
            )
        }
    ) { _ ->
        LazyColumn(
            modifier = Modifier.padding(horizontal = 10.dp),
            state = state,
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            items(sections) { section ->
                TitledLinesSectionItem(
                    section = section,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}
