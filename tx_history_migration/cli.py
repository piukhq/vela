from typer import Argument, Option, Typer, echo

from .polaris_db import get_existing_history_txs_ids
from .processed_txs_handler import VelaTxHistoryHandler

cli = Typer(name="Transaction History Migration", no_args_is_help=True)

# pylint: disable=too-complex
@cli.command(no_args_is_help=True)
def run(
    retailer_slug: str = Argument(...),
    polaris_db_name: str = Option("polaris"),
    batch_size: int = Option(1000, min=10, max=5000),
    debug: bool = Option(False, help="If set to True logs the activity payload instead of sending it."),
    max_txs_to_process: int = Option(
        None,
        min=1,
        help=(
            "Instead of processing all transactions in batches, "
            "fetches and processes the provided number of transactions in a single batch then stops."
        ),
    ),
) -> None:
    echo("Starting script...")
    current_batch = 0  # pylint: disable=invalid-name
    existing_history_txs_ids = get_existing_history_txs_ids(polaris_db_name, retailer_slug)

    if max_txs_to_process:
        batch_size = max_txs_to_process

    with VelaTxHistoryHandler(batch_size, retailer_slug, existing_history_txs_ids, debug=debug) as handler:
        tx_to_process_count = handler.get_processed_tx_count()

        msg = f"{tx_to_process_count:d} transactions to process, will process "
        if max_txs_to_process:
            msg += f"up to {max_txs_to_process:d} transactions and stop."
            estimated_tot_batches = 1

        else:
            msg += f"in batches of {handler.batch_size:d}"
            estimated_tot_batches = tx_to_process_count // handler.batch_size

            if tx_to_process_count % handler.batch_size != 0:
                estimated_tot_batches += 1

        echo(msg)
        try:
            while True:
                current_batch += 1
                processed_txs_data = handler.fetch_batch()
                if not processed_txs_data:
                    break

                echo(f"processing batch {current_batch:d}/{estimated_tot_batches:d}")
                for tx_data in processed_txs_data:
                    handler.produce_activity(tx_data)

                if max_txs_to_process:
                    break

        except KeyboardInterrupt:
            echo("Script manually interupted, exiting...")

    echo("Finished.")


@cli.callback()
def callback() -> None:
    """
    command line interface
    """


if __name__ == "__main__":
    cli()
