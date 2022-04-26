"""Tests for the patito.validators module."""
from datetime import date, datetime
from typing import Literal, Optional

import patito as pt
import polars as pl
import pytest
from patito.exceptions import ValidationError
from patito.validators import validate


def test_missing_column_validation():
    """Validation should catch missing columns."""

    class SingleColumnModel(pt.Model):
        column_1: int
        column_2: str

    # First we raise an error because we are missing column_1
    with pytest.raises(ValidationError) as e_info:
        validate(dataframe=pl.DataFrame(), schema=SingleColumnModel)

    errors = e_info.value.errors()
    assert len(e_info.value.errors()) == 2
    assert sorted(errors, key=lambda e: e["loc"]) == [
        {
            "loc": ("column_1",),
            "msg": "Missing column",
            "type": "type_error.missingcolumns",
        },
        {
            "loc": ("column_2",),
            "msg": "Missing column",
            "type": "type_error.missingcolumns",
        },
    ]


def test_superflous_column_validation():
    """Validation should catch superflous columns."""

    class SingleColumnModel(pt.Model):
        column_1: int

    # We raise an error because we have added column_2
    with pytest.raises(ValidationError) as e_info:
        validate(
            dataframe=pl.DataFrame().with_columns(
                [
                    pl.lit(1).alias("column_1"),
                    pl.lit(2).alias("column_2"),
                ]
            ),
            schema=SingleColumnModel,
        )

    errors = e_info.value.errors()
    assert len(e_info.value.errors()) == 1
    assert errors[0] == {
        "loc": ("column_2",),
        "msg": "Superflous column",
        "type": "type_error.superflouscolumns",
    }


def test_validate_non_nullable_columns():
    """Test for validation logic related to missing values."""

    class SmallModel(pt.Model):
        column_1: int
        column_2: Optional[int]

    # We insert nulls into a non-optional column, causing an exception
    wrong_nulls_df = pl.DataFrame().with_columns(
        [
            pl.lit(None).cast(pl.Int64).alias("column_1"),
            pl.lit(None).cast(pl.Int64).alias("column_2"),
        ]
    )
    with pytest.raises(ValidationError) as e_info:
        validate(
            dataframe=wrong_nulls_df,
            schema=SmallModel,
        )

    errors = e_info.value.errors()
    assert len(e_info.value.errors()) == 1
    assert errors[0] == {
        "loc": ("column_1",),
        "msg": "1 missing value",
        "type": "value_error.missingvalues",
    }


def test_validate_dtype_checks():
    """Test dtype-checking logic."""
    # An integer field may be validated against several different integer dtypes
    class IntModel(pt.Model):
        column: int

    for dtype in (pl.Int8, pl.Int16, pl.Int32, pl.Int64):
        series = pl.Series([], dtype=dtype).alias("column")
        dataframe = pl.DataFrame([series])
        validate(dataframe=dataframe, schema=IntModel)

    # But other types, including floating point types, must be considered invalid
    for dtype in (pl.Utf8, pl.Date, pl.Float32, pl.Float64):
        series = pl.Series([], dtype=dtype).alias("column")
        dataframe = pl.DataFrame([series])
        with pytest.raises(ValidationError) as e_info:
            validate(dataframe=dataframe, schema=IntModel)

        errors = e_info.value.errors()
        assert len(e_info.value.errors()) == 1
        assert errors[0] == {
            "loc": ("column",),
            "msg": f"Polars dtype {dtype} does not match model field type.",
            "type": "type_error.columndtype",
        }

    # We construct a model with most of the common field types
    class CompleteModel(pt.Model):
        int_column: int
        string_column: str
        float_column: float
        datetime_column: datetime
        date_column: date
        bool_column: bool

    # And validate it againt a valid dataframe
    valid_df = pl.DataFrame().with_columns(
        [
            pl.lit(1, dtype=pl.Int16).alias("int_column"),
            pl.lit("a", dtype=pl.Utf8).alias("string_column"),
            pl.lit(1.0, dtype=pl.Float32).alias("float_column"),
            pl.lit(datetime.now(), dtype=pl.Datetime).alias("datetime_column"),
            pl.lit(date.today(), dtype=pl.Date).alias("date_column"),
            pl.lit(True, dtype=pl.Boolean).alias("bool_column"),
        ]
    )
    validate(dataframe=valid_df, schema=CompleteModel)

    # We try to hit each column dtype check
    for column in CompleteModel.columns:
        if column == "int_column":
            dtype = pl.Float64
        else:
            dtype = pl.Int64

        with pytest.raises(ValidationError) as e_info:
            validate(
                dataframe=valid_df.with_column(pl.lit(1, dtype=dtype).alias(column)),
                schema=CompleteModel,
            )

        errors = e_info.value.errors()
        assert len(e_info.value.errors()) == 1

        assert errors[0] == {
            "loc": (column,),
            "msg": f"Polars dtype {dtype} does not match model field type.",
            "type": "type_error.columndtype",
        }


def test_datetime_validation():
    """
    Test for date(time) validation.

    Both strings, dates, and datetimes are assigned type "string" in the OpenAPI JSON
    schema spec, so this needs to be specifically tested for since the implementation
    needs to check the "format" property on the field schema.
    """

    string_df = pl.DataFrame().with_column(pl.lit("string", dtype=pl.Utf8).alias("c"))
    date_df = pl.DataFrame().with_column(pl.lit(date.today(), dtype=pl.Date).alias("c"))
    datetime_df = pl.DataFrame().with_column(
        pl.lit(datetime.now(), dtype=pl.Datetime).alias("c")
    )

    class StringModel(pt.Model):
        c: str

    validate(dataframe=string_df, schema=StringModel)
    with pytest.raises(ValidationError):
        validate(dataframe=date_df, schema=StringModel)
    with pytest.raises(ValidationError):
        validate(dataframe=datetime_df, schema=StringModel)

    class DateModel(pt.Model):
        c: date

    validate(dataframe=date_df, schema=DateModel)
    with pytest.raises(ValidationError):
        validate(dataframe=string_df, schema=DateModel)
    with pytest.raises(ValidationError):
        validate(dataframe=datetime_df, schema=DateModel)

    class DateTimeModel(pt.Model):
        c: datetime

    validate(dataframe=datetime_df, schema=DateTimeModel)
    with pytest.raises(ValidationError):
        validate(dataframe=string_df, schema=DateTimeModel)
    with pytest.raises(ValidationError):
        validate(dataframe=date_df, schema=DateTimeModel)


def test_enum_validation():
    """Test validation of enum-typed fields."""

    class EnumModel(pt.Model):
        column: Literal["a", "b", "c"]

    valid_df = pl.DataFrame({"column": ["a", "b", "b", "c"]})
    validate(dataframe=valid_df, schema=EnumModel)

    invalid_df = pl.DataFrame({"column": ["d"]})
    with pytest.raises(ValidationError) as e_info:
        validate(dataframe=invalid_df, schema=EnumModel)

    errors = e_info.value.errors()
    assert len(errors) == 1
    assert errors[0] == {
        "loc": ("column",),
        "msg": "Rows with invalid values: {'d'}.",
        "type": "value_error.rowvalue",
    }


def test_uniqueness_constraint_validation():
    """Uniqueness constraints should be validated."""

    class UniqueModel(pt.Model):
        product_id: int = pt.Field(unique=True)

    validate(dataframe=pl.DataFrame({"product_id": [1, 2]}), schema=UniqueModel)

    with pytest.raises(ValidationError) as e_info:
        validate(dataframe=pl.DataFrame({"product_id": [1, 1]}), schema=UniqueModel)

    errors = e_info.value.errors()
    assert len(errors) == 1
    assert errors[0] == {
        "loc": ("product_id",),
        "msg": "2 rows with duplicated values.",
        "type": "value_error.rowvalue",
    }


def test_validation_of_bounds_checks():
    """Check if value bounds are correctly validated."""

    class BoundModel(pt.Model):
        le_column: float = pt.Field(le=42.5)
        lt_column: float = pt.Field(lt=42.5)
        ge_column: float = pt.Field(ge=42.5)
        gt_column: float = pt.Field(gt=42.5)
        combined_column: float = pt.Field(gt=42.5, le=43)
        multiple_column: float = pt.Field(multiple_of=0.5)
        const_column: float = pt.Field(default=3.1415, const=True)
        regex_column: str = pt.Field(regex=r"value [A-Z]")
        min_length_column: str = pt.Field(min_length=2)
        max_length_column: str = pt.Field(max_length=2)

    # The .example() method should produce the correct dtypes, except for
    # the regex-validated string field which is not supported
    BoundModel.validate(
        BoundModel.example({"regex_column": ["value A", "value B", "value C"]})
    )

    valid = [42.5, 42.4, 42.5, 42.6, 42.6, 19.5, 3.1415, "value X", "ab", "ab"]
    valid_df = pl.DataFrame(data=[valid], columns=BoundModel.columns)
    BoundModel.validate(valid_df)

    invalid = [42.6, 42.5, 42.4, 42.5, 43.1, 19.75, 3.2, "value x", "a", "abc"]
    for column_index, column_name in enumerate(BoundModel.columns):
        data = (
            valid[:column_index]
            + invalid[column_index : column_index + 1]
            + valid[column_index + 1 :]
        )
        invalid_df = pl.DataFrame(data=[data], columns=BoundModel.columns)
        with pytest.raises(ValidationError) as e_info:
            BoundModel.validate(invalid_df)
        errors = e_info.value.errors()
        assert len(errors) == 1
        assert errors[0] == {
            "loc": (column_name,),
            "msg": "1 row with out of bound values.",
            "type": "value_error.rowvalue",
        }


def test_validation_of_dtype_specifiers():
    """Fields with specific dtype annotations should be validated."""

    class DTypeModel(pt.Model):
        int_column: int
        int_explicit_dtype_column: int = pt.Field(dtype=pl.Int64)
        smallint_column: int = pt.Field(dtype=pl.Int8)
        unsigned_int_column: int = pt.Field(dtype=pl.UInt64)
        unsigned_smallint_column: int = pt.Field(dtype=pl.UInt8)

    assert DTypeModel.dtypes == {
        "int_column": pl.Int64,
        "int_explicit_dtype_column": pl.Int64,
        "smallint_column": pl.Int8,
        "unsigned_int_column": pl.UInt64,
        "unsigned_smallint_column": pl.UInt8,
    }

    # The .example() method should produce the correct dtypes
    DTypeModel.validate(DTypeModel.example({"smallint_column": [1, 2, 3]}))

    valid = [
        pl.Series([-2]).cast(pl.Int64),
        pl.Series([2**32]).cast(pl.Int64),
        pl.Series([2]).cast(pl.Int8),
        pl.Series([2]).cast(pl.UInt64),
        pl.Series([2]).cast(pl.UInt8),
    ]
    valid_df = pl.DataFrame(data=valid, columns=DTypeModel.columns)
    DTypeModel.validate(valid_df)

    invalid = [
        pl.Series([2.5]).cast(pl.Float64),
        pl.Series([2.5]).cast(pl.Float64),
        pl.Series([2**32]).cast(pl.Int64),
        pl.Series([-2]).cast(pl.Int64),
        pl.Series([-2]).cast(pl.Int64),
    ]
    for column_index, (column_name, dtype) in enumerate(
        zip(
            DTypeModel.columns,
            [pl.Float64, pl.Float64, pl.Int64, pl.Int64, pl.Int64],
        )
    ):
        data = (
            valid[:column_index]
            + invalid[column_index : column_index + 1]
            + valid[column_index + 1 :]
        )
        invalid_df = pl.DataFrame(data=data, columns=DTypeModel.columns)
        with pytest.raises(ValidationError) as e_info:
            DTypeModel.validate(invalid_df)
        errors = e_info.value.errors()
        assert len(errors) == 1
        assert errors[0] == {
            "loc": (column_name,),
            "msg": f"Polars dtype {dtype} does not match model field type.",
            "type": "type_error.columndtype",
        }


def test_custom_constraint_validation():
    """Users should be able to specify custom constraints."""

    class CustomConstraintModel(pt.Model):
        even_int: int = pt.Field(
            constraints=[(pl.col("even_int") % 2 == 0).alias("even_constraint")]
        )
        odd_int: int = pt.Field(constraints=pl.col("odd_int") % 2 == 1)

    df = CustomConstraintModel.DataFrame({"even_int": [2, 3], "odd_int": [1, 2]})
    with pytest.raises(ValidationError) as e_info:
        df.validate()
    errors = e_info.value.errors()
    assert len(errors) == 2
    assert errors[0] == {
        "loc": ("even_int",),
        "msg": "1 row does not match custom constraints.",
        "type": "value_error.rowvalue",
    }
    assert errors[1] == {
        "loc": ("odd_int",),
        "msg": "1 row does not match custom constraints.",
        "type": "value_error.rowvalue",
    }
    df.limit(1).validate()