package com.gabstra.myworkoutassistant.shared.sets

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import java.util.UUID

data class RestSet(override val id: UUID, val timeInSeconds: Int, val subCategory: SetSubCategory = SetSubCategory.WorkSet): Set(id)
