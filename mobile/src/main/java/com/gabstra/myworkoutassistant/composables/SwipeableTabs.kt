package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextStyle
import kotlin.math.abs

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SwipeableTabs(
    tabTitles: List<String>,
    selectedTabIndex: Int,
    onTabSelected: (Int) -> Unit,
    modifier: Modifier = Modifier,
    tabRowModifier: Modifier = Modifier.fillMaxWidth(),
    pagerModifier: Modifier = Modifier.fillMaxSize(),
    tabTextStyle: TextStyle = MaterialTheme.typography.bodyMedium,
    tabEnabled: (Int) -> Boolean = { true },
    renderPager: Boolean = true,
    containerColor: Color = MaterialTheme.colorScheme.background,
    contentColor: Color = MaterialTheme.colorScheme.onBackground,
    selectedContentColor: Color = MaterialTheme.colorScheme.primary,
    unselectedContentColor: Color = MaterialTheme.colorScheme.onBackground,
    pageContent: @Composable (Int) -> Unit = {},
) {
    if (tabTitles.isEmpty()) return

    val clampedSelectedIndex = selectedTabIndex.coerceIn(0, tabTitles.lastIndex)
    val pagerState = rememberPagerState(
        initialPage = clampedSelectedIndex,
        pageCount = { tabTitles.size }
    )
    val activeTabIndex = if (renderPager) pagerState.currentPage else clampedSelectedIndex

    if (renderPager) {
        LaunchedEffect(clampedSelectedIndex, tabTitles.size) {
            if (clampedSelectedIndex == pagerState.currentPage) {
                return@LaunchedEffect
            }
            val pageDistance = abs(clampedSelectedIndex - pagerState.currentPage)
            if (pageDistance > 1) {
                pagerState.scrollToPage(clampedSelectedIndex)
            } else {
                pagerState.animateScrollToPage(clampedSelectedIndex)
            }
        }

        LaunchedEffect(pagerState.currentPage) {
            if (pagerState.currentPage != clampedSelectedIndex) {
                onTabSelected(pagerState.currentPage)
            }
        }
    }

    Column(modifier = modifier) {
        TabRow(
            modifier = tabRowModifier.then(
                if (renderPager) {
                    Modifier
                } else {
                    Modifier.pointerInput(clampedSelectedIndex, tabTitles.size) {
                        var dragTotal = 0f
                        detectHorizontalDragGestures(
                            onHorizontalDrag = { _, dragAmount ->
                                dragTotal += dragAmount
                            },
                            onDragEnd = {
                                val swipeThresholdPx = 48f
                                if (abs(dragTotal) >= swipeThresholdPx) {
                                    val direction = if (dragTotal < 0f) 1 else -1
                                    val targetIndex =
                                        (clampedSelectedIndex + direction).coerceIn(0, tabTitles.lastIndex)
                                    if (targetIndex != clampedSelectedIndex) {
                                        onTabSelected(targetIndex)
                                    }
                                }
                                dragTotal = 0f
                            },
                            onDragCancel = { dragTotal = 0f }
                        )
                    }
                }
            ),
            containerColor = containerColor,
            contentColor = contentColor,
            selectedTabIndex = activeTabIndex,
            indicator = { tabPositions ->
                TabRowDefaults.Indicator(
                    Modifier.tabIndicatorOffset(tabPositions[activeTabIndex]),
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

        if (renderPager) {
            HorizontalPager(
                modifier = pagerModifier,
                state = pagerState,
            ) { pageIndex ->
                pageContent(pageIndex)
            }
        }
    }
}
