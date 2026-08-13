package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SecondaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme

private const val PAGINATED_TAB_PAGE_SIZE = 3
private val COMPACT_TAB_ARROW_SIZE = 32.dp

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SwipeableTabs(
    tabTitles: List<String>,
    selectedTabIndex: Int,
    onTabSelected: (Int) -> Unit,
    modifier: Modifier = Modifier,
    tabRowModifier: Modifier = Modifier.fillMaxWidth(),
    pagerModifier: Modifier = Modifier.fillMaxSize(),
    tabTextStyle: TextStyle = MaterialTheme.typography.bodySmall,
    tabEnabled: (Int) -> Boolean = { true },
    compactNavigation: Boolean = false,
    renderPager: Boolean = true,
    containerColor: Color = MaterialTheme.colorScheme.background,
    contentColor: Color = MaterialTheme.colorScheme.onBackground,
    selectedContentColor: Color = MaterialTheme.colorScheme.primary,
    unselectedContentColor: Color = MaterialTheme.colorScheme.onBackground,
    pageContent: @Composable (Int) -> Unit = {},
) {
    if (tabTitles.isEmpty()) return

    val clampedSelectedIndex = selectedTabIndex.coerceIn(0, tabTitles.lastIndex)
    val activeTabIndex = clampedSelectedIndex
    val pagerState = rememberPagerState(
        initialPage = clampedSelectedIndex,
        pageCount = { tabTitles.size },
    )
    var compactTabPageStart by remember(tabTitles.size) {
        mutableIntStateOf(
            (clampedSelectedIndex / PAGINATED_TAB_PAGE_SIZE) * PAGINATED_TAB_PAGE_SIZE
        )
    }

    LaunchedEffect(activeTabIndex, compactNavigation) {
        if (compactNavigation) {
            compactTabPageStart =
                (activeTabIndex / PAGINATED_TAB_PAGE_SIZE) * PAGINATED_TAB_PAGE_SIZE
        }
    }

    LaunchedEffect(clampedSelectedIndex, renderPager) {
        if (renderPager && pagerState.currentPage != clampedSelectedIndex) {
            pagerState.scrollToPage(clampedSelectedIndex)
        }
    }

    Column(modifier = modifier) {
        if (compactNavigation) {
            val lastTabPageStart =
                (tabTitles.lastIndex / PAGINATED_TAB_PAGE_SIZE) * PAGINATED_TAB_PAGE_SIZE
            val tabPageStart = compactTabPageStart.coerceIn(0, lastTabPageStart)
            val visibleTabTitles = tabTitles.subList(
                tabPageStart,
                minOf(tabPageStart + PAGINATED_TAB_PAGE_SIZE, tabTitles.size),
            )
            val previousTabPageIndex = tabPageStart - PAGINATED_TAB_PAGE_SIZE
            val nextTabPageIndex = tabPageStart + PAGINATED_TAB_PAGE_SIZE
            val previousTabPageEnabled = previousTabPageIndex >= 0
            val nextTabPageEnabled = nextTabPageIndex < tabTitles.size
            val showTabPageArrows = tabTitles.size > PAGINATED_TAB_PAGE_SIZE

            Box(
                modifier = tabRowModifier,
            ) {
                HorizontalDivider(
                    modifier = Modifier.align(Alignment.BottomCenter),
                    color = MaterialTheme.colorScheme.outlineVariant,
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                if (showTabPageArrows) Box(
                    modifier = Modifier
                        .size(COMPACT_TAB_ARROW_SIZE)
                        .clickable(
                            enabled = previousTabPageEnabled,
                            onClick = { compactTabPageStart = previousTabPageIndex },
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "Previous tab page",
                        modifier = Modifier.size(20.dp),
                        tint = if (previousTabPageEnabled) contentColor else DisabledContentGray,
                    )
                }
                Row(
                    modifier = Modifier
                        .weight(1f),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    repeat(PAGINATED_TAB_PAGE_SIZE) { visibleIndex ->
                        val title = visibleTabTitles.getOrNull(visibleIndex)
                        Box(modifier = Modifier.weight(1f)) {
                            if (title != null) {
                                val tabIndex = tabPageStart + visibleIndex
                                Tab(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(56.dp),
                                    selected = tabIndex == activeTabIndex,
                                    enabled = tabEnabled(tabIndex),
                                    onClick = { onTabSelected(tabIndex) },
                                    text = {
                                        Text(
                                            text = title,
                                            style = tabTextStyle,
                                            textAlign = TextAlign.Center,
                                            maxLines = 2,
                                            softWrap = true,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                    },
                                    selectedContentColor = selectedContentColor,
                                    unselectedContentColor = unselectedContentColor,
                                )
                                if (tabIndex == activeTabIndex) {
                                    Box(
                                        modifier = Modifier
                                            .align(Alignment.BottomCenter)
                                            .fillMaxWidth()
                                            .height(2.dp)
                                            .background(selectedContentColor),
                                    )
                                }
                            }
                        }
                    }
                }
                if (showTabPageArrows) Box(
                    modifier = Modifier
                        .size(COMPACT_TAB_ARROW_SIZE)
                        .clickable(
                            enabled = nextTabPageEnabled,
                            onClick = { compactTabPageStart = nextTabPageIndex },
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                        contentDescription = "Next tab page",
                        modifier = Modifier.size(20.dp),
                        tint = if (nextTabPageEnabled) contentColor else DisabledContentGray,
                    )
                }
            }
            }
        } else {
            SecondaryTabRow(
                modifier = tabRowModifier,
                containerColor = containerColor,
                contentColor = contentColor,
                selectedTabIndex = activeTabIndex,
                indicator = {
                    TabRowDefaults.SecondaryIndicator(
                        modifier = Modifier.tabIndicatorOffset(activeTabIndex),
                        color = selectedContentColor,
                    )
                }
            ) {
                tabTitles.forEachIndexed { index, title ->
                    Tab(
                        selected = index == activeTabIndex,
                        enabled = tabEnabled(index),
                        onClick = { onTabSelected(index) },
                        text = {
                            Text(
                                text = title,
                                style = tabTextStyle
                            )
                        },
                        selectedContentColor = selectedContentColor,
                        unselectedContentColor = unselectedContentColor,
                    )
                }
            }
        }

        if (renderPager) {
            HorizontalPager(
                state = pagerState,
                modifier = pagerModifier,
                userScrollEnabled = false,
                beyondViewportPageCount = 0,
            ) { pageIndex ->
                pageContent(pageIndex)
            }
        }
    }
}

@Preview(
    name = "Paginated home tabs",
    showBackground = true,
    widthDp = 412,
    heightDp = 240,
)
@Composable
private fun PaginatedHomeTabsPreview() {
    PaginatedHomeTabsPreviewContent(initialSelectedTabIndex = 1)
}

@Preview(
    name = "Paginated home tabs - second page",
    showBackground = true,
    widthDp = 412,
    heightDp = 240,
)
@Composable
private fun PaginatedHomeTabsSecondPagePreview() {
    PaginatedHomeTabsPreviewContent(initialSelectedTabIndex = 3)
}

@Composable
private fun PaginatedHomeTabsPreviewContent(initialSelectedTabIndex: Int) {
    var selectedTabIndex by remember { mutableIntStateOf(initialSelectedTabIndex) }
    val tabTitles = listOf("Status", "Workouts", "Gear", "Alarms", "Library")

    MyWorkoutAssistantTheme {
        SwipeableTabs(
            tabTitles = tabTitles,
            selectedTabIndex = selectedTabIndex,
            onTabSelected = { selectedTabIndex = it },
            compactNavigation = true,
        ) { pageIndex ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(text = "${tabTitles[pageIndex]} page")
            }
        }
    }
}
