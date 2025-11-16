package com.gabstra.myworkoutassistant.shared.setdata

data class RestSetData(val startTimer: Int,val endTimer: Int, val subCategory: SetSubCategory = SetSubCategory.WorkSet): SetData()