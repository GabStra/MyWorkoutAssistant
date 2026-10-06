package com.gabstra.myworkoutassistant.shared

import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight

// Bundled Roboto v2.138 (Apache License 2.0) so mobile and wear render the
// identical typeface regardless of system font availability.
val AppFontFamily = FontFamily(
    Font(R.font.roboto_regular, FontWeight.Normal),
    Font(R.font.roboto_medium, FontWeight.Medium),
    Font(R.font.roboto_bold, FontWeight.Bold),
)
