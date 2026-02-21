package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray

/** A section with a title and a list of lines (e.g. "Equipment" / ["Barbell"] or "Accessories" / ["Bench", "Rings"]). */
data class TitledLinesSection(val title: String, val lines: List<String>)

@Composable
private fun TitledLinesSectionItem(
    section: TitledLinesSection,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Text(
            text = section.title,
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = LighterGray,
            textAlign = TextAlign.Center
        )
        section.lines.forEach { line ->
            Text(
                text = line,
                modifier = Modifier.padding(top = 4.dp).fillMaxWidth(),
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Normal),
                color = MediumLighterGray,
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
    val scrollState = rememberScrollState()
    ScreenScaffold(
        modifier = modifier.fillMaxSize(),
        scrollState = scrollState,
        scrollIndicator = {
            ScrollIndicator(
                state = scrollState,
                colors = ScrollIndicatorDefaults.colors(
                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                    trackColor = MediumDarkGray
                )
            )
        }
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(scrollState),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            sections.forEach { section ->
                TitledLinesSectionItem(
                    section = section,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}
